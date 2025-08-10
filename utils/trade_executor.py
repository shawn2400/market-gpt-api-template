# utils/trade_executor.py
import os
import logging
from typing import Dict, Any, Optional

from utils import config
from utils.ws_fallback import get_price, is_price_fresh
from utils.binance_trader import binance_futures_trade  # async

PRICE_PROTECT_PCT = float(getattr(config, "PRICE_PROTECT_PCT", 0.25))
PRICE_MAX_AGE_SEC = int(getattr(config, "PRICE_MAX_AGE_SEC", 10))
SKIP_MUTATIONS = (str(getattr(config, "BINANCE_SKIP_ACCOUNT_MUTATIONS",
                              os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "true"))).lower() == "true")

def _norm_direction(d: str) -> str:
    d = (d or "").strip().upper()
    if d in ("LONG", "BUY"): return "LONG"
    if d in ("SHORT", "SELL"): return "SHORT"
    return "LONG"

async def execute_trade_live(
    symbol: str,
    entry: Optional[float],
    stop: Optional[float],
    tp: Optional[float],
    direction: str,
    leverage: int = 20,
    budget_usd: float = 100,
    market_type: str = "futures",
    price_protect_pct: Optional[float] = None,
    quantity: Optional[float] = None,
) -> Dict[str, Any]:
    try:
        symbol = str(symbol).upper()
        direction = _norm_direction(direction)
        pprotect = float(price_protect_pct or PRICE_PROTECT_PCT)

        if SKIP_MUTATIONS:
            msg = "BINANCE_SKIP_ACCOUNT_MUTATIONS=true — פעולות כתיבה מושבתות עד שה-IP יאושר ב-Binance."
            logging.error(f"[TRADE] {msg}")
            return {"status": "error", "error": msg, "code": "mutations_disabled"}

        live_price = await get_price(symbol)
        if live_price is None or not is_price_fresh(symbol, max_age_sec=PRICE_MAX_AGE_SEC):
            logging.error(f"[TRADE] ❌ מחיר חי לא תקין/לא עדכני ל-{symbol}: {live_price}")
            return {"status": "error", "error": "live price unavailable or stale"}

        if entry is None:
            entry = float(live_price)

        entry = float(entry)
        stop  = float(stop) if stop is not None else None
        tp    = float(tp)   if tp is not None else None

        if stop is None or tp is None:
            return {"status": "error", "error": "sl/tp required (supply or predict before calling)"}

        if direction == "LONG" and not (stop < entry < tp):
            return {"status": "error", "error": f"levels invalid for LONG (entry={entry}, stop={stop}, tp={tp})"}
        if direction == "SHORT" and not (tp < entry < stop):
            return {"status": "error", "error": f"levels invalid for SHORT (entry={entry}, stop={stop}, tp={tp})"}

        deviation = abs((live_price - entry) / entry) * 100.0
        if deviation > pprotect:
            logging.warning(f"[TRADE] ⚠️ סטיית מחיר {deviation:.4f}% בין תוכנית ({entry}) ללייב ({live_price}) – נחסם")
            return {"status": "error", "error": f"price deviation {deviation:.4f}% > {pprotect}%", "entry": entry, "live_price": live_price}

        try:
            result = await binance_futures_trade(
                symbol=symbol, side=direction, entry=entry, sl=stop, tp=tp,
                leverage=int(leverage), budget=float(budget_usd),
                quantity=quantity, market_type=market_type
            )
            logging.info(f"[TRADE] {direction} {symbol} live={live_price} entry={entry} (dev={deviation:.4f}%) -> {result}")
            return {"status": "success", "result": result}
        except Exception as e:
            msg = str(e)
            # פירוק שגיאות נפוצות והכוונה
            if "quantity too small" in msg and "minQty" in msg:
                return {"status": "error", "error": "quantity_below_minQty", "hint": "הגדל תקציב או הפחת מינוף/סימבול עם step קטן יותר", "raw": msg}
            if "notional too small" in msg:
                return {"status": "error", "error": "notional_too_small", "hint": "הגדל תקציב או בחר סימבול זול יותר", "raw": msg}
            raise

    except Exception as e:
        logging.error("[TRADE] שגיאה בביצוע טרייד %s: %s", symbol, e, exc_info=True)
        return {"status": "error", "error": str(e)}


















































