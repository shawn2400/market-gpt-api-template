# utils/trade_executor.py
import os
import logging
from typing import Dict, Any, Optional, Tuple

import pandas as pd
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange

from utils import config
from utils.ws_fallback import get_price, is_price_fresh, snapshot_klines_df
from utils.btc_anchor import compute_btc_anchor
from utils.precision_utils import (
    apply_price_tick, apply_qty_step, calc_quantity_from_budget
)

# נתיבי כתיבה (אם זמינים)
_futures_ok = True
_spot_ok = True
try:
    from utils.binance_trader import binance_futures_trade  # async
except Exception as _e:
    _futures_ok = False
    logging.warning("[TRADE] futures writer unavailable: %s", _e)

try:
    from utils.binance_trader import binance_spot_trade  # async
except Exception as _e:
    _spot_ok = False
    logging.warning("[TRADE] spot writer unavailable: %s", _e)

# הגנות
PRICE_PROTECT_PCT = float(getattr(config, "PRICE_PROTECT_PCT", 0.25))  # אחוזים
PRICE_MAX_AGE_SEC = int(getattr(config, "PRICE_MAX_AGE_SEC", 10))

# שליטה על כתיבה לבורסה
EXECUTE_TRADES = bool(getattr(config, "EXECUTE_TRADES", False))
BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV = str(
    getattr(
        config,
        "BINANCE_SKIP_ACCOUNT_MUTATIONS",
        os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "true")
    )
).lower() in ("1", "true", "yes", "y", "on")

MUTATIONS_DISABLED = (not EXECUTE_TRADES) or BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV

# פרופיל רמות (ATR-מכפילים) — תואם “Fast Reply”
_SL_K = 0.60
_TP1_K = 1.80
_TP2_K = 3.20

def _norm_direction(d: str) -> str:
    d = (d or "").strip().upper()
    if d in ("LONG", "BUY"):
        return "LONG"
    if d in ("SHORT", "SELL"):
        return "SHORT"
    return "LONG"

def _validate_inputs(symbol: str,
                     direction: str,
                     market_type: str,
                     quantity: Optional[float]) -> Optional[str]:
    if not symbol or not isinstance(symbol, str):
        return "symbol required"
    if direction not in ("LONG", "SHORT"):
        return "direction must be LONG or SHORT"
    mt = (market_type or "futures").lower().strip()
    if mt not in ("futures", "spot"):
        return "market_type must be 'futures' or 'spot'"
    if mt == "futures" and not _futures_ok:
        return "futures trade path unavailable"
    if mt == "spot" and not _spot_ok:
        return "spot trade path unavailable"
    if quantity is not None and quantity <= 0:
        return "quantity must be > 0 if provided"
    return None

def _quick_risk_metrics(symbol: str, interval: str = "15m", limit: int = 120) -> Dict[str, Optional[float]]:
    try:
        df: pd.DataFrame = snapshot_klines_df(symbol, interval=interval, limit=limit, market_type="futures")
        if df is None or df.empty:
            return {"atr": None, "atrp": None, "adx": None}
        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        atr14 = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()
        adx14 = ADXIndicator(high=high, low=low, close=close, window=14).adx()
        atr = float(atr14.iloc[-1])
        adx = float(adx14.iloc[-1])
        last = float(close.iloc[-1])
        atrp = (atr / last * 100.0) if last > 0 else None
        return {"atr": atr, "atrp": atrp, "adx": adx, "last": last}
    except Exception as e:
        logging.warning(f"[TRADE] quick risk metrics failed for {symbol}: {e}")
        return {"atr": None, "atrp": None, "adx": None, "last": None}

def _auto_leverage(atrp: Optional[float], adx: Optional[float], btc_strength: Optional[float], quality: Optional[float]) -> int:
    q = float(quality or 7.0)
    base = 10.0 + max(0.0, min(14.0, (q - 6.0) * 3.5))   # 6→10, 10→24
    boost = 0.0
    if adx is not None:
        boost += max(0.0, min(6.0, (float(adx) - 20.0) * 0.3))
    if btc_strength is not None:
        boost += max(0.0, min(5.0, (float(btc_strength) - 55.0) * 0.15))
    penalty = 0.0
    if atrp is not None:
        if atrp >= 2.0: penalty = 10.0
        elif atrp >= 1.2: penalty = 6.0
        elif atrp >= 0.8: penalty = 3.0
    lev = base + boost - penalty
    return int(max(5.0, min(35.0, round(lev))))

def _levels_from_atr(direction: str, entry: float, atr: float) -> Tuple[float, float, float]:
    """
    מחזיר (sl, tp1, tp2) לא לעיגון דיוק (זה יקרה בהמשך).
    """
    if direction == "LONG":
        sl = entry - _SL_K * atr
        tp1 = entry + _TP1_K * atr
        tp2 = entry + _TP2_K * atr
    else:
        sl = entry + _SL_K * atr
        tp1 = entry - _TP1_K * atr
        tp2 = entry - _TP2_K * atr
    return sl, tp1, tp2

async def execute_trade_live(
    symbol: str,
    entry: Optional[float],
    stop: Optional[float],
    tp: Optional[float],
    direction: str,
    leverage: Optional[int] = None,      # אם None → יחושב אוטומטית
    budget_usd: float = 100,
    market_type: str = "futures",
    price_protect_pct: Optional[float] = None,
    quantity: Optional[float] = None,    # אם מגיעה כמות — גוברת על תקציב
    quality_score: Optional[float] = None,
) -> Dict[str, Any]:
    """
    ביצוע טרייד חי (Spot/Futures) עם:
    - מינוף אוטומטי (אם לא סופק)
    - חישוב SL/TP אוטומטי (אם לא סופק) על בסיס ATR
    - חישוב כמות מה-Budget×Leverage (אם לא סופקה)
    - עיגון Price/Qty לפי exchangeInfo (tick/step/minNotional)
    - אימות מחיר לייב + סטיית מחיר מותרת
    - DRY-RUN אם כתיבה מושבתת
    """
    try:
        symbol = str(symbol).upper().strip()
        direction = _norm_direction(direction)
        market_type = (market_type or "futures").lower().strip()
        pprotect = float(price_protect_pct) if price_protect_pct is not None else PRICE_PROTECT_PCT

        err = _validate_inputs(symbol, direction, market_type, quantity)
        if err:
            logging.error("[TRADE] invalid inputs: %s", err)
            return {"status": "error", "error": err, "code": "invalid_inputs"}

        # מחיר חי
        live_price = await get_price(symbol)
        if live_price is None or not is_price_fresh(symbol, max_age_sec=PRICE_MAX_AGE_SEC):
            logging.error(f"[TRADE] ❌ מחיר חי לא תקין/לא עדכני ל-{symbol}: {live_price}")
            return {"status": "error", "error": "live price unavailable or stale", "code": "stale_price"}

        # אם לא הועבר entry — נשתמש במחיר חי
        if entry is None:
            entry = float(live_price)

        # מדדי סיכון מהירים (ATR/ADX/ATR%)
        risk = _quick_risk_metrics(symbol, interval="15m", limit=120)
        atr = risk.get("atr")
        adx = risk.get("adx")
        atrp = risk.get("atrp")

        # חישוב מינוף אוטומטי אם לא סופק (Futures בלבד)
        if leverage is None and market_type == "futures":
            anchor = await compute_btc_anchor(frames=("15m",), market="futures")
            btc_strength = float(anchor.get("strength", 0.0) or 0.0)
            leverage = _auto_leverage(atrp, adx, btc_strength, quality_score)

        lev_for_calc = int(leverage or 1)

        # אם SL/TP לא נמסרו — חישוב אוטומטי
        if (stop is None or tp is None) and (atr is not None):
            sl, tp1, tp2 = _levels_from_atr(direction, float(entry), float(atr))
            # בנתיב ביצוע אנחנו משתמשים ב-TP1 כברירת מחדל; TP2 נוח להצגה בתוכנית.
            if stop is None:
                stop = sl
            if tp is None:
                tp = tp1

        # עיגון דיוק/טיק למחירים (entry/stop/tp)
        entry_adj, entry_str = apply_price_tick(float(entry), symbol)
        stop_adj, stop_str = (apply_price_tick(float(stop), symbol) if stop is not None else (None, ""))
        tp_adj, tp_str = (apply_price_tick(float(tp), symbol) if tp is not None else (None, ""))

        entry = entry_adj
        stop = stop_adj
        tp = tp_adj

        # סדר מחירים חייב להיות תקין
        if stop is None or tp is None:
            return {"status": "error", "error": "sl/tp required and could not be derived", "code": "missing_levels"}

        if direction == "LONG":
            if not (stop < entry < tp):
                return {"status": "error", "error": f"levels invalid for LONG (entry={entry}, stop={stop}, tp={tp})", "code": "levels_order"}
        else:
            if not (tp < entry < stop):
                return {"status": "error", "error": f"levels invalid for SHORT (entry={entry}, stop={stop}, tp={tp})", "code": "levels_order"}

        # סטיית מחיר מול לייב — pprotect באחוזים
        deviation_pct = abs((live_price - entry) / entry) * 100.0
        if deviation_pct > pprotect:
            logging.warning(f"[TRADE] ⚠️ סטיית מחיר {deviation_pct:.4f}% בין תוכנית ({entry}) ללייב ({live_price}) – נחסם (> {pprotect}%)")
            return {
                "status": "error",
                "error": f"price deviation {deviation_pct:.4f}% > {pprotect}%",
                "code": "price_deviation",
                "entry": entry,
                "live_price": live_price,
                "deviation_pct": round(deviation_pct, 6),
            }

        # חישוב כמות אם לא נמסרה: Budget×Leverage / Entry
        qty_out = None
        if quantity is None:
            qres = calc_quantity_from_budget(symbol, price=entry, budget_usd=float(budget_usd), leverage=float(lev_for_calc if market_type == "futures" else 1.0))
            if not qres.get("ok"):
                return {"status": "error", "error": f"quantity calc failed: {qres.get('reason')}", "code": "qty_calc_failed"}
            quantity = float(qres["qty"])
            qty_out = qres["qty_str"]
        else:
            # עיגון ידני ל-step אם סופקה כמות
            quantity, qty_out = apply_qty_step(float(quantity), symbol)

        # DRY-RUN אם כתיבה מושבתת
        if MUTATIONS_DISABLED:
            msg_flags = []
            if not EXECUTE_TRADES: msg_flags.append("EXECUTE_TRADES=false")
            if BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV: msg_flags.append("BINANCE_SKIP_ACCOUNT_MUTATIONS=true")
            msg = " & ".join(msg_flags) or "mutations disabled"

            # חישוב TP2 להצגה (לא לביצוע)
            tp2_disp = None
            if atr is not None:
                _, _tp1, _tp2 = _levels_from_atr(direction, float(entry), float(atr))
                tp2_disp, _ = apply_price_tick(_tp2, symbol)

            return {
                "status": "dry_run",
                "reason": msg,
                "plan": {
                    "symbol": symbol,
                    "side": direction,
                    "entry": entry,
                    "entry_str": entry_str,
                    "sl": stop,
                    "sl_str": stop_str,
                    "tp": tp,
                    "tp_str": tp_str,
                    "tp2_preview": tp2_disp,
                    "leverage": (lev_for_calc if market_type == "futures" else None),
                    "budget": float(budget_usd),
                    "quantity": quantity,
                    "quantity_str": qty_out,
                    "market_type": market_type,
                    "live_price": live_price,
                    "deviation_pct": round(deviation_pct, 6),
                    "atr": float(atr) if atr is not None else None,
                    "adx": float(adx) if adx is not None else None,
                },
            }

        # ביצוע בפועל (כתיבה לבורסה)
        if market_type == "futures":
            result = await binance_futures_trade(
                symbol=symbol,
                side=direction,
                entry=entry,
                sl=stop,
                tp=tp,
                leverage=int(lev_for_calc),
                budget=float(budget_usd),
                quantity=quantity,
                market_type=market_type
            )
        else:
            result = await binance_spot_trade(
                symbol=symbol,
                side=direction,
                entry=entry,
                sl=stop,
                tp=tp,
                budget=float(budget_usd),
                quantity=quantity
            )

        logging.info(f"[TRADE] ✅ {market_type.upper()} {direction} {symbol} live={live_price} entry={entry} -> {result}")
        return {"status": "success", "result": result}

    except Exception as e:
        logging.error("[TRADE] שגיאה בביצוע טרייד %s: %s", symbol, e, exc_info=True)
        return {"status": "error", "error": str(e), "code": "exception"}




















































