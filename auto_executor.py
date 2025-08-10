# utils/trade_executor.py
import os
import logging
from typing import Dict, Any, Optional

from utils import config
from utils.ws_fallback import (
    get_price as get_price_cached,   # לשיקוף טריות
    get_price_smart,                 # מודע ל-ban/418
    is_price_fresh,
)
from utils.binance_trader import binance_futures_trade  # async

PRICE_PROTECT_PCT = float(getattr(config, "PRICE_PROTECT_PCT", 0.25))
PRICE_MAX_AGE_SEC = int(getattr(config, "PRICE_MAX_AGE_SEC", 10))
SKIP_MUTATIONS = (str(getattr(config, "BINANCE_SKIP_ACCOUNT_MUTATIONS",
                              os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "true"))).lower() == "true")

def _norm_direction(d: str) -> str:
    d = (d or "").strip().upper()
    if d in ("LONG", "BUY"):
        return "LONG"
    if d in ("SHORT", "SELL"):
        return "SHORT"
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
    """
    ביצוע טרייד חי עם הגנות:
    - מחיר לייב דרך get_price_smart (WS תחילה; REST רק אם מותר, עם מודעות-באן)
    - אימות טריות/היגיון רמות (SL/TP מול כיוון)
    - Price deviation guard מול entry המבוקש
    - כיבוד דגל BINANCE_SKIP_ACCOUNT_MUTATIONS לבטיחות
    """
    try:
        symbol = str(symbol).upper()
        direction = _norm_direction(direction)
        pprotect = float(price_protect_pct or PRICE_PROTECT_PCT)

        # מניעת פעולות כתיבה כשמופעל דגל בטיחות
        if SKIP_MUTATIONS:
            msg = "BINANCE_SKIP_ACCOUNT_MUTATIONS=true — פעולות כתיבה מושבתות עד שה-IP יאושר/ה-ban יוסר."
            logging.error("[TRADE] %s", msg)
            return {"status": "error", "error": msg, "code": "mutations_disabled"}

        # מחיר חי מודע ל-ban
        live_price = None
        cache_price = None
        try:
            live_price = await get_price_smart(symbol)
            cache_price = await get_price_cached(symbol)  # לשיקוף טריות
        except Exception as e:
            logging.warning("[TRADE] live price fetch failed for %s: %s", symbol, e)

        fresh = bool(cache_price is not None and is_price_fresh(symbol, max_age_sec=PRICE_MAX_AGE_SEC))

        if entry is None:
            if live_price is None:
                return {
                    "status": "error",
                    "error": f"live price unavailable (WS stale and REST cooldown/ban) for {symbol}"
                }
            entry = float(live_price)

        # ולידציות רמות
        entry = float(entry)
        stop  = float(stop) if stop is not None else None
        tp    = float(tp)   if tp is not None else None

        if stop is None or tp is None:
            return {"status": "error", "error": "sl/tp required (supply or predict before calling)"}

        if direction == "LONG" and not (stop < entry < tp):
            return {"status": "error", "error": f"levels invalid for LONG (entry={entry}, stop={stop}, tp={tp})"}
        if direction == "SHORT" and not (tp < entry < stop):
            return {"status": "error", "error": f"levels invalid for SHORT (entry={entry}, stop={stop}, tp={tp})"}

        # אם יש מחיר חי – נגן על סטייה מול entry
        if live_price is not None:
            deviation = abs((live_price - entry) / entry) * 100.0
            if deviation > pprotect:
                logging.warning("[TRADE] ⚠️ סטיית מחיר %.4f%% בין תוכנית (%.8f) ללייב (%.8f) – נחסם",
                                deviation, entry, live_price)
                return {
                    "status": "error",
                    "error": f"price deviation {deviation:.4f}% > {pprotect}%",
                    "entry": entry,
                    "live_price": live_price
                }
        else:
            # אין live_price (למשל בזמן cooldown) – אפשר לבחור לחסום או לאפשר לפי מדיניות.
            # ברירת מחדל: חוסם כדי לא להיכנס בעיניים עצומות.
            return {
                "status": "error",
                "error": "no live price available (cooldown/ban); aborting to protect execution"
            }

        # אזהרת טריות (לא חוסם, כי יש לנו מספר חי מה-smart)
        if not fresh:
            logging.info("[TRADE] WS cache stale for %s (> %ss) but smart price is present; continuing.",
                         symbol, PRICE_MAX_AGE_SEC)

        # ביצוע בפועל
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
        logging.info("[TRADE] %s %s entry=%.8f live=%.8f -> %s", direction, symbol, entry, live_price, result)
        return {"status": "success", "result": result}

    except Exception as e:
        logging.error("[TRADE] שגיאה בביצוע טרייד %s: %s", symbol if 'symbol' in locals() else "?", e, exc_info=True)
        return {"status": "error", "error": str(e)}









































































