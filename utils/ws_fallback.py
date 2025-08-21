# utils/ws_fallback.py
import asyncio
import time
import logging
from typing import Dict, Any

LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
logger = logging.getLogger("algogpt.ws")


def update_price(symbol: str, price: float) -> None:
    LAST_PRICE_CACHE[symbol.upper()] = {
        "price": price,
        "ts": time.time()
    }


def get_price(symbol: str) -> float | None:
    return LAST_PRICE_CACHE.get(symbol.upper(), {}).get("price")


def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    info = LAST_PRICE_CACHE.get(symbol.upper())
    if not info:
        return False
    return (time.time() - info.get("ts", 0)) <= max_age_sec


# ✅ WS Auto Updater עם age_sec בלוג
async def auto_price_updater(symbols: list[str], interval: int = 15):
    """
    מושך מחירים מ-Binance כל X שניות ומעדכן ב-cache.
    רושם לוג INFO עם age_sec (כמה זמן עבר מאז עדכון קודם).
    """
    from utils.binance_client import futures_mark_price

    while True:
        now = time.time()
        for sym in symbols:
            try:
                price = futures_mark_price(sym)

                # חשב age_sec אם יש נתון קודם
                prev_ts = LAST_PRICE_CACHE.get(sym.upper(), {}).get("ts", None)
                age_sec = round(now - prev_ts, 2) if prev_ts else None

                update_price(sym, price)
                logger.info({
                    "event": "price_update",
                    "symbol": sym,
                    "price": price,
                    "age_sec": age_sec
                })
            except Exception as e:
                logger.error({
                    "event": "price_update_error",
                    "symbol": sym,
                    "error": str(e)
                })
        await asyncio.sleep(interval)



























