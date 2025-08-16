# utils/trade_executor.py
import os
import logging
from typing import Dict, Any, Optional

import pandas as pd
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange

from utils import config
from utils.ws_fallback import get_price, is_price_fresh, snapshot_klines_df
from utils.btc_anchor import compute_btc_anchor

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
        if atrp >= 2.0:
            penalty = 10.0
        elif atrp >= 1.2:
            penalty = 6.0
        elif atrp >= 0.8:
            penalty = 3.0
    lev = base + boost - penalty
    return int(max(5.0, min(35.0, round(lev))))

def _quick_risk_metrics(symbol: str, interval: str = "15m", limit: int = 120) -> Dict[str, Optional[float]]:
    try:
        df: pd.DataFrame = snapshot_klines_df(symbol, interval=interval, limit=limit, market_type="futures")
        if df is None or df.empty:
            return {"atrp": None, "adx": None}
        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        atr14 = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()
        adx14 = ADXIndicator(high=high, low=low, close=close, window=14).adx()
        atr = float(atr14.iloc[-1])
        adx = float(adx14.iloc[-1])
        last = float(close.iloc[-1])
        atrp = (atr / last * 100.0) if last > 0 else None
        return {"atrp": atrp, "adx": adx}
    except Exception as e:
        logging.warning(f"[TRADE] quick risk metrics failed for {symbol}: {e}")
        return {"atrp": None, "adx": None}

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
    ביצוע טרייד חי (Spot/Futures) עם הגנות + מינוף אוטומטי אם לא סופק.
    - אימות מחיר לייב + טריות (WS)
    - Price deviation guard מול entry המבוקש
    - כיבוד EXECUTE_TRADES/BINANCE_SKIP_ACCOUNT_MUTATIONS
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

        # תקינות מספרים
        try:
            entry = float(entry)
            stop  = float(stop) if stop is not None else None
            tp    = float(tp)   if tp is not None else None
        except Exception:
            return {"status": "error", "error": "entry/stop/tp must be numeric", "code": "bad_levels"}

        if stop is None or tp is None:
            return {"status": "error", "error": "sl/tp required (supply or predict before calling)", "code": "missing_levels"}

        # סדר מחירים חייב להיות תקין
        if direction == "LONG":
            if not (stop < entry < tp):
                return {
                    "status": "error",
                    "error": f"levels invalid for LONG (entry={entry}, stop={stop}, tp={tp})",
                    "code": "levels_order"
                }
        else:
            if not (tp < entry < stop):
                return {
                    "status": "error",
                    "error": f"levels invalid for SHORT (entry={entry}, stop={stop}, tp={tp})",
                    "code": "levels_order"
                }

        # חישוב מינוף אוטומטי אם לא סופק
        if leverage is None and market_type == "futures":
            anchor = await compute_btc_anchor(frames=("15m",), market="futures")
            btc_strength = float(anchor.get("strength", 0.0) or 0.0)
            risk = _quick_risk_metrics(symbol, interval="15m", limit=120)
            leverage = _auto_leverage(risk.get("atrp"), risk.get("adx"), btc_strength, quality_score)

        lev_for_log = leverage if (market_type == "futures") else None

        # סטיית מחיר מול לייב — pprotect באחוזים (למשל 0.25)
        deviation_pct = abs((live_price - entry) / entry) * 100.0
        if deviation_pct > pprotect:
            logging.warning(
                f"[TRADE] ⚠️ סטיית מחיר {deviation_pct:.4f}% בין תוכנית ({entry}) ללייב ({live_price}) – נחסם (> {pprotect}%)"
            )
            return {
                "status": "error",
                "error": f"price deviation {deviation_pct:.4f}% > {pprotect}%",
                "code": "price_deviation",
                "entry": entry,
                "live_price": live_price,
                "deviation_pct": round(deviation_pct, 6),
            }

        # DRY-RUN אם כתיבה מושבתת
        if MUTATIONS_DISABLED:
            reason = []
            if not EXECUTE_TRADES:
                reason.append("EXECUTE_TRADES=false")
            if BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV:
                reason.append("BINANCE_SKIP_ACCOUNT_MUTATIONS=true")
            msg = " & ".join(reason) or "mutations disabled"
            logging.info("[TRADE] DRY-RUN (%s): %s %s entry=%s sl=%s tp=%s lev=%s budget=%s qty=%s live=%s dev=%.4f%%",
                         msg, direction, symbol, entry, stop, tp, lev_for_log, budget_usd, quantity, live_price, deviation_pct)
            return {
                "status": "dry_run",
                "reason": msg,
                "plan": {
                    "symbol": symbol,
                    "side": direction,
                    "entry": entry,
                    "sl": stop,
                    "tp": tp,
                    "leverage": lev_for_log,
                    "budget": float(budget_usd),
                    "quantity": quantity,
                    "market_type": market_type,
                    "live_price": live_price,
                    "deviation_pct": round(deviation_pct, 6),
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
                leverage=int(leverage or 10),
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

        logging.info(
            f"[TRADE] ✅ {market_type.upper()} {direction} {symbol} live={live_price} entry={entry} (dev={deviation_pct:.4f}%) -> {result}"
        )
        return {"status": "success", "result": result}

    except Exception as e:
        logging.error("[TRADE] שגיאה בביצוע טרייד %s: %s", symbol, e, exc_info=True)
        return {"status": "error", "error": str(e), "code": "exception"}




















































