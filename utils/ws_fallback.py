# utils/ws_fallback.py
import asyncio
import logging
import time
from typing import Dict, Optional
from utils.redis_client import set_value, get_value

logger = logging.getLogger("algogpt.ws_fallback")

# fallback בזיכרון
LAST_PRICE_CACHE: Dict[str, Dict[str, float]] = {}

# כמה זמן נחשב מחיר "טרי"
FRESHNESS_SEC = 10


async def price_monitor_loop():
    """
    לופ שרץ ברקע ושומר מחירים מה־WS או מ־REST
    """
    while True:
        # כרגע placeholder - אפשר להרחיב לחיבור WS
        await asyncio.sleep(5)


def update_price(symbol: str, price: float):
    """
    עדכון מחיר גם בזיכרון וגם ב־Redis
    """
    ts = time.time()
    LAST_PRICE_CACHE[symbol.upper()] = {"price": price, "ts": ts}

    # שמירה ב־Redis
    set_value(f"price:{symbol.upper()}", str(price), expire=60)
    logger.debug(f"[WS] Updated {symbol}={price}")


def get_price(symbol: str) -> Optional[float]:
    """
    החזרת מחיר מה־cache (Redis > Memory)
    """
    symbol = symbol.upper()

    # קודם Redis
    val = get_value(f"price:{symbol}")
    if val:
        try:
            return float(val)
        except Exception:
            pass

    # fallback לזיכרון
    data = LAST_PRICE_CACHE.get(symbol)
    if data:
        return data["price"]

    return None


def is_price_fresh(symbol: str) -> bool:
    """
    בדיקה אם המחיר בזיכרון עדיין טרי (<= FRESHNESS_SEC)
    """
    symbol = symbol.upper()
    data = LAST_PRICE_CACHE.get(symbol)
    if not data:
        return False
    age = time.time() - data["ts"]
    return age <= FRESHNESS_SEC























