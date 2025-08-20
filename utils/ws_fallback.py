# utils/ws_fallback.py
import time
import logging
import threading

logger = logging.getLogger("algogpt.ws_fallback")

# Cache מחירים אחרונים
LAST_PRICE_CACHE: dict[str, dict] = {}

def update_price(symbol: str, price: float):
    """עדכון מחיר אחרון ב־cache"""
    LAST_PRICE_CACHE[symbol.upper()] = {"price": float(price), "ts": time.time()}
    logger.debug(f"[WS] Updated {symbol}={price}")

def get_price(symbol: str) -> float | None:
    """החזרת מחיר עדכני מה־cache"""
    return LAST_PRICE_CACHE.get(symbol.upper(), {}).get("price")

def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    """בודק אם המחיר עדכני"""
    info = LAST_PRICE_CACHE.get(symbol.upper())
    if not info:
        return False
    return (time.time() - info.get("ts", 0)) <= max_age_sec

def price_monitor_loop(interval: int = 30):
    """לולאת ניטור (fallback) – רצה ברקע"""
    def loop():
        while True:
            logger.debug(f"[WS] Cache size={len(LAST_PRICE_CACHE)}")
            time.sleep(interval)
    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread



























