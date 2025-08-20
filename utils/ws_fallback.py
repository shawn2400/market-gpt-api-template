# utils/ws_fallback.py
import time, logging, asyncio
from utils.json_logger import get_trace_logger

_prices: dict[str, tuple[float, float]] = {}  # {symbol: (price, timestamp)}
logger = logging.getLogger("algogpt")


def update_price(symbol: str, price: float):
    _prices[symbol] = (price, time.time())


def get_price(symbol: str) -> float | None:
    return _prices.get(symbol, (None, None))[0]


def is_price_fresh(symbol: str, max_age_sec: int = 10, trace_id: str | None = None) -> bool:
    _, ts = _prices.get(symbol, (None, None))
    trace_logger = get_trace_logger(trace_id)
    if ts is None:
        trace_logger.warning({"event": "price_check", "symbol": symbol, "status": "missing"})
        return False
    age = time.time() - ts
    if age > max_age_sec:
        trace_logger.error({"event": "price_check", "symbol": symbol, "status": "stale", "age_sec": round(age, 1)})
        return False
    return True


async def price_monitor_loop(interval_sec: int = 5, max_age_sec: int = 10):
    while True:
        for symbol, (_, ts) in list(_prices.items()):
            age = time.time() - ts
            if age > max_age_sec:
                trace_logger = get_trace_logger()
                trace_logger.error({"event": "price_monitor", "symbol": symbol, "status": "stale", "age_sec": round(age, 1)})
        await asyncio.sleep(interval_sec)



















