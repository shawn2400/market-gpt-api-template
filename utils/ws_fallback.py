import time
import logging

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


















