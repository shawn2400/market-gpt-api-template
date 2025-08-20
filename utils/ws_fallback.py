# utils/ws_fallback.py
import time, logging, asyncio

_prices: dict[str, tuple[float, float]] = {}  # {symbol: (price, timestamp)}
logger = logging.getLogger("algogpt.ws")

def update_price(symbol: str, price: float):
    _prices[symbol] = (price, time.time())

def get_price(symbol: str) -> float | None:
    return _prices.get(symbol, (None, None))[0]

def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    """בודק אם המחיר האחרון עדכני"""
    _, ts = _prices.get(symbol, (None, None))
    if ts is None:
        logger.warning(f"[WS] No price yet for {symbol}")
        return False
    age = time.time() - ts
    if age > max_age_sec:
        logger.error(f"[WS] Price for {symbol} stale: {age:.1f}s (>{max_age_sec})")
        return False
    return True

async def price_monitor_loop(interval_sec: int = 5, max_age_sec: int = 10):
    """לולאה ברקע שבודקת מחירים ישנים מדי"""
    while True:
        for symbol, (_, ts) in list(_prices.items()):
            age = time.time() - ts
            if age > max_age_sec:
                logger.error(f"[WS-MONITOR] {symbol} stale: {age:.1f}s")
        await asyncio.sleep(interval_sec)



















