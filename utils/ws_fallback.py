# utils/ws_fallback.py
import asyncio
import logging
import time
from typing import Dict, Any, Optional

logger = logging.getLogger("algogpt.ws_fallback")

# Cache מחירים אחרונים
LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}

# עדכון מחיר ב־cache
def update_price(symbol: str, price: float) -> None:
    LAST_PRICE_CACHE[symbol.upper()] = {
        "price": float(price),
        "ts": time.time()
    }

# שליפה של מחיר אחרון
def get_price(symbol: str) -> Optional[float]:
    info = LAST_PRICE_CACHE.get(symbol.upper())
    if info:
        return info.get("price")
    return None

# בדיקה אם מחיר טרי
def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    info = LAST_PRICE_CACHE.get(symbol.upper())
    if not info:
        return False
    age = time.time() - info.get("ts", 0)
    return age <= max_age_sec

# לולאת price monitor (פשוטה — אפשר להרחיב בעתיד)
async def price_monitor_loop():
    """
    לולאה שמנטרת ומרעננת cache (אם אין WS).
    כרגע היא רק רצה כל כמה שניות ושומרת לוג.
    """
    while True:
        await asyncio.sleep(5)
        logger.debug(f"[WS-Fallback] cache size = {len(LAST_PRICE_CACHE)}")


























