# utils/ws_fallback.py
import time
import logging
import asyncio
from utils.redis_client import redis_client  # ✅ Redis client

_prices: dict[str, tuple[float, float]] = {}  # {symbol: (price, timestamp)}
logger = logging.getLogger("algogpt.ws")


def update_price(symbol: str, price: float):
    """
    מעדכן מחיר בזיכרון המקומי וגם ב־Redis (אם זמין).
    """
    ts = time.time()
    _prices[symbol] = (price, ts)
    logger.info({
        "event": "price_update",
        "symbol": symbol,
        "price": price,
        "timestamp": ts,
        "source": "update_price"
    })

    # שמירה ב־Redis עם פג תוקף
    if redis_client:
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(redis_client.set(symbol, price, ex=30))
            else:
                loop.run_until_complete(redis_client.set(symbol, price, ex=30))
        except Exception as e:
            logger.warning(f"[WS] Failed storing {symbol} in Redis: {e}")


def get_price(symbol: str) -> float | None:
    return _prices.get(symbol, (None, None))[0]


def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    """בודק אם המחיר האחרון עדכני"""
    _, ts = _prices.get(symbol, (None, None))
    if ts is None:
        logger.warning({"event": "price_check", "symbol": symbol, "status": "missing"})
        return False
    age = time.time() - ts
    if age > max_age_sec:
        logger.error({"event": "price_check", "symbol": symbol, "status": "stale", "age_sec": round(age, 1)})
        return False
    return True


async def price_monitor_loop(interval_sec: int = 5, max_age_sec: int = 10):
    """לולאה ברקע שבודקת מחירים ישנים מדי"""
    while True:
        for symbol, (_, ts) in list(_prices.items()):
            age = time.time() - ts
            if age > max_age_sec:
                logger.error({"event": "price_monitor", "symbol": symbol, "status": "stale", "age_sec": round(age, 1)})
        await asyncio.sleep(interval_sec)






















