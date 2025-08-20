import time
import logging
import asyncio

_prices: dict[str, tuple[float, float]] = {}  # {symbol: (price, timestamp)}
logger = logging.getLogger("algogpt")

def update_price(symbol: str, price: float):
    _prices[symbol] = (price, time.time())

def get_price(symbol: str) -> float | None:
    return _prices.get(symbol, (None, None))[0]

def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    _, ts = _prices.get(symbol, (None, None))
    if ts is None:
        logger.warning(f"[WS] No price data yet for {symbol}")
        return False

    age = time.time() - ts
    if age > max_age_sec:
        logger.error(f"[WS] Price for {symbol} is stale! Age={age:.1f}s (> {max_age_sec}s)")
        return False
    return True

async def price_monitor_loop(interval_sec: int = 5, max_age_sec: int = 10):
    """
    🔄 לולאת בדיקה שרצה ברקע ובודקת אם יש מחירים ישנים מדי.
    נרשם ל-logs אם מחיר לא מתעדכן.
    """
    while True:
        for symbol, (_, ts) in list(_prices.items()):
            age = time.time() - ts
            if age > max_age_sec:
                logger.error(f"[WS-MONITOR] {symbol} price stale: {age:.1f}s old (> {max_age_sec}s)")
        await asyncio.sleep(interval_sec)



















