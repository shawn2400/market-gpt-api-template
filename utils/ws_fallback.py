# utils/ws_fallback.py
import time
import logging
import asyncio

_prices: dict[str, tuple[float, float]] = {}  # {symbol: (price, timestamp)}
logger = logging.getLogger("algogpt.ws")

def update_price(symbol: str, price: float):
    """עדכון מחיר פנימי בזיכרון"""
    _prices[symbol] = (price, time.time())
    logger.info({
        "event": "price_update",
        "symbol": symbol,
        "price": price,
        "timestamp": _prices[symbol][1]
    })

def get_price(symbol: str) -> float | None:
    """מחזיר מחיר עדכני אם קיים"""
    return _prices.get(symbol, (None, None))[0]

def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    """בודק אם המחיר עדכני לפי הזמן האחרון שהתקבל"""
    price, ts = _prices.get(symbol, (None, None))
    if ts is None:
        logger.warning({
            "event": "price_check",
            "symbol": symbol,
            "status": "missing",
            "msg": "No price data yet"
        })
        return False

    age = time.time() - ts
    if age > max_age_sec:
        logger.error({
            "event": "price_check",
            "symbol": symbol,
            "status": "stale",
            "age_sec": round(age, 1),
            "threshold_sec": max_age_sec,
            "price": price
        })
        return False

    logger.debug({
        "event": "price_check",
        "symbol": symbol,
        "status": "fresh",
        "age_sec": round(age, 1),
        "price": price
    })
    return True

async def price_monitor_loop(interval_sec: int = 5, max_age_sec: int = 10):
    """
    🔄 לולאת בדיקה ברקע שמנטרת מחירים ישנים מדי.
    כותבת שגיאה ללוג אם המחיר התיישן.
    """
    while True:
        now = time.time()
        for symbol, (price, ts) in list(_prices.items()):
            age = now - ts
            if age > max_age_sec:
                logger.error({
                    "event": "price_monitor",
                    "symbol": symbol,
                    "status": "stale",
                    "age_sec": round(age, 1),
                    "threshold_sec": max_age_sec,
                    "price": price
                })
        await asyncio.sleep(interval_sec)





















