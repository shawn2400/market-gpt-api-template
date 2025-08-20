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

# ✅ NEW: לולאה שמעדכנת אוטומטית את כל ה-watchlist
async def auto_price_updater(symbols: list[str], interval: int = 15):
    """
    מושך מחירים מ-Binance כל X שניות ומעדכן ב-cache
    """
    from utils.binance_client import futures_mark_price

    while True:
        for sym in symbols:
            try:
                price = futures_mark_price(sym)
                update_price(sym, price)
                logger.info(f"[WS] Updated {sym} → {price}")
            except Exception as e:
                logger.error(f"[WS] Failed to update {sym}: {e}")
        await asyncio.sleep(interval)


























