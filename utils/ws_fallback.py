# utils/ws_fallback.py
import asyncio
import time
import logging
import os
from typing import Dict, Any
from utils.json_logger import setup_json_logging

logger = setup_json_logging()

LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}

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

# ✅ Auto price updater
async def auto_price_updater(symbols: list[str]):
    """
    מושך מחירים מ-Binance כל X שניות (WS_UPDATE_INTERVAL) ומעדכן ב-cache
    """
    from utils.binance_client import futures_mark_price
    interval = int(os.getenv("WS_UPDATE_INTERVAL", 15))

    logger.info({"event": "ws_updater", "msg": f"🔄 Auto price updater started (interval={interval}s)"})

    while True:
        for sym in symbols:
            try:
                price = futures_mark_price(sym)
                update_price(sym, price)
                logger.info({
                    "event": "price_update",
                    "symbol": sym,
                    "price": price,
                    "msg": f"[WS] Updated {sym} → {price}"
                })
            except Exception as e:
                logger.error({
                    "event": "price_update_failed",
                    "symbol": sym,
                    "error": str(e)
                })
        await asyncio.sleep(interval)


























