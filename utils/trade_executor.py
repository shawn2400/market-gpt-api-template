# utils/trade_executor.py
import os
import logging
from typing import Dict, Any

from utils.ws_fallback import get_price, is_price_fresh
from utils.binance_trader import binance_futures_trade  # נניח async ותקין

PRICE_PROTECT_PCT = float(os.getenv("PRICE_PROTECT_PCT", "0.10"))  # אחוז

def _norm_direction(d: str) -> str:
    d = (d or "").strip().upper()
    if d in ("LONG", "BUY"): return "LONG"
    if d in ("SHORT", "SELL"): return "SHORT"
    return "LONG"

async def execute_trade_live(
    symbol: str,
    entry: float,
    stop: float,
    tp: float,
    direction: str,
    leverage: int = 20,
    budget_usd: float = 100,
    market_type: str = "futures",
    price_protect_pct: float | None = None
) -> Dict[str, Any]:
    """
    מבצע טרייד חי עם הגנות:
    - אימות מחיר לייב + טריות
    - Price deviation guard
    - החזרה תמיד dict
    """
    price_protect_pct = float(price_protect_pct or PRICE_PROTECT_PCT)
    try:
        symbol = str(symbol).upper()
        direction = _norm_direction(direction)
        entry = float(entry); stop = float(stop); tp = float(tp)

        # ולידציה בסיסית לפי כיוון
        if direction == "LONG" and not (stop < entry < tp):
            return {"status": "error", "error": f"levels invalid for LONG (entry={entry}, stop={stop}, tp={tp})"}
        if direction == "SHORT" and not (tp < entry < stop):
            return {"status": "error", "error": f"levels invalid for SHORT (entry={entry}, stop={stop}, tp={tp})"}

        # מחיר חי
        live_price = await get_price(symbol)
        if live_price is None or not is_price_fresh(symbol, max_age_sec=10):
            logging.error(f"[TRADE] ❌ מחיר חי לא תקין/לא עדכני ל-{symbol}: {live_price}")
            return {"status": "error", "error": "live price unavailable or stale"}

        deviation = abs((live_price - entry) / entry) * 100.0
        if deviation > price_protect_pct:
            logging.warning(f"[TRADE] ⚠️ סטיית מחיר {deviation:.4f}% בין תוכנית ({entry}) ללייב ({live_price}) – נחסם")
            return {
                "status": "error",
                "error": f"price deviation {deviation:.4f}% > {price_protect_pct}%",
                "entry": entry,
                "live_price": live_price
            }

        # ביצוע בפועל (הפונקציה הא-סינכרונית חיצונית)
        result = await binance_futures_trade(
            symbol=symbol,
            side=direction,
            entry=live_price,  # נכנסים במחיר לייב שאומת
            sl=stop,
            tp=tp,
            leverage=int(leverage),
            budget=float(budget_usd),
            market_type=market_type
        )

        logging.info(f"[TRADE] {direction} {symbol} price={live_price} (dev={deviation:.4f}%) -> {result}")
        return {"status": "success", "result": result}

    except Exception as e:
        logging.error(f"[TRADE] שגיאה בביצוע טרייד {symbol}: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}














































