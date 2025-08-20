# utils/ws_fallback.py
import asyncio
import time
import logging
import random
from utils.redis_client import set_value, get_value

logger = logging.getLogger("algogpt.ws_fallback")

# In-memory cache
price_cache: dict[str, tuple[float, float]] = {}  # symbol → (price, timestamp)


async def update_price(symbol: str, price: float) -> None:
    """
    עדכון מחיר במטמון מקומי וב־Redis
    """
    now = time.time()
    price_cache[symbol] = (price, now)

    # שמירה גם ב־Redis (עם TTL = 30 שניות)
    try:
        set_value(f"price:{symbol}", str(price), expire=30)
    except Exception as e:
        logger.error(f"[ws_fallback] Failed to cache {symbol} in Redis: {e}")


def get_price(symbol: str) -> float | None:
    """
    מחזיר מחיר עדכני – קודם מה־Redis אם זמין, אחרת מה־cache
    """
    try:
        redis_val = get_value(f"price:{symbol}")
        if redis_val:
            return float(redis_val)
    except Exception:
        pass

    if symbol in price_cache:
        return price_cache[symbol][0]
    return None


def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    """
    בודק אם מחיר עדכני (מתוך cache / Redis)
    """
    try:
        redis_val = get_value(f"price:{symbol}")
        if redis_val:
            return True
    except Exception:
        pass

    if symbol in price_cache:
        _, ts = price_cache[symbol]
        return (time.time() - ts) <= max_age_sec
    return False


async def price_monitor_loop():
    """
    לולאת דמו שמעדכנת מחירים רנדומליים כל 5 שניות
    בפועל כאן יתחבר WebSocket ל־Binance
    """
    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    while True:
        for sym in symbols:
            price = random.uniform(10000, 70000)  # דמו
            await update_price(sym, price)
            logger.info({"event": "price_update", "symbol": sym, "price": price})
        await asyncio.sleep(5)






















