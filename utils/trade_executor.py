# utils/trade_executor.py
import os
import logging
from typing import Dict, Any, Optional

from utils import config
from utils.ws_fallback import get_price, is_price_fresh

# ייבוא נתיבי כתיבה — ננסה להביא גם Spot וגם Futures
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

# הגדרות הגנה
PRICE_PROTECT_PCT = float(getattr(config, "PRICE_PROTECT_PCT", 0.25))  # אחוזים (0.25% דיפולט)
PRICE_MAX_AGE_SEC = int(getattr(config, "PRICE_MAX_AGE_SEC", 10))

# --- שליטה מרכזית על כתיבה לבורסה ---
EXECUTE_TRADES = bool(getattr(config, "EXECUTE_TRADES", False))
BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV = str(
    getattr(
        config,
        "BINANCE_SKIP_ACCOUNT_MUTATIONS",
        os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "true")
    )
).lower() in ("1", "true", "yes", "y", "on")

# אם אחד משני הבלמים פעיל -> אין כתיבה
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
                     leverage: int,
                     budget_usd: float,
                     market_type: str,
                     quantity: Optional[float]) -> Optional[str]:
    if not symbol or not isinstance(symbol, str):
        return "symbol required"
    if direction not in ("LONG", "SHORT"):
        return "direction must be LONG or SHORT"
    if leverage <= 0 and market_type == "futures":
        return "leverage must be > 0 for futures"
    if budget_usd <= 0 and (quantity is None or quantity <= 0):
        # חייבים או תקציב חיובי או כמות חיובית
        return "either budget_usd > 0 or quantity > 0 required"
    mt = (market_type or "futures").lower().strip()
    if mt not in ("futures", "spot"):
        return "market_type must be 'futures' or 'spot'"
    if mt == "futures" and not _futures_ok:
        return "futures trade path unavailable"
    if mt == "spot" and not _spot_ok:
        return "spot trade path unavailable"
    return None


async def execute_trade_live(
    symbol: str,
    entry: Optional[float],
    stop: Optional[float],
    tp: Optional[float],
    direction: str,
    leverage: int = 20,           # בשימוש רק ב-futures
    budget_usd: float = 100,
    market_type: str = "futures", # "futures" או "spot"
    price_protect_pct: Optional[float] = None,
    quantity: Optional[float] = None,  # אם מגיעה כמות — גוברת על תקציב
) -> Dict[str, Any]:
    """
    ביצוע טרייד חי (Spot/Futures) עם הגנות:
    - אימות מחיר לייב + טריות (WS)
    - Price deviation guard מול entry המבוקש
    - כיבוד EXECUTE_TRADES/BINANCE_SKIP_ACCOUNT_MUTATIONS
    - ולידציות בסיסיות לקלטים
    """
    try:
        symbol = str(symbol).upper().strip()
        direction = _norm_direction(direction)
        market_type = (market_type or "futures").lower().strip()
        pprotect = float(price_protect_pct) if price_protect_pct is not None else PRICE_PROTECT_PCT

        # ולידציות בסיסיות
        err = _validate_inputs(symbol, direction, int(leverage), float(budget_usd), market_type, quantity)
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
        else:  # SHORT
            if not (tp < entry < stop):
                return {
                    "status": "error",
                    "error": f"levels invalid for SHORT (entry={entry}, stop={stop}, tp={tp})",
                    "code": "levels_order"
                }

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

        # אם כתיבה מושבתת — החזר DRY-RUN שימושי
        if MUTATIONS_DISABLED:
            reason = []
            if not EXECUTE_TRADES:
                reason.append("EXECUTE_TRADES=false")
            if BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV:
                reason.append("BINANCE_SKIP_ACCOUNT_MUTATIONS=true")
            msg = " & ".join(reason) or "mutations disabled"
            logging.info("[TRADE] DRY-RUN (%s): %s %s entry=%s sl=%s tp=%s lev=%s budget=%s qty=%s live=%s dev=%.4f%%",
                         msg, direction, symbol, entry, stop, tp, leverage, budget_usd, quantity, live_price, deviation_pct)
            return {
                "status": "dry_run",
                "reason": msg,
                "plan": {
                    "symbol": symbol,
                    "side": direction,
                    "entry": entry,
                    "sl": stop,
                    "tp": tp,
                    "leverage": int(leverage) if market_type == "futures" else None,
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
                leverage=int(leverage),
                budget=float(budget_usd),
                quantity=quantity,
                market_type=market_type
            )
        else:  # spot
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




















































