# utils/ws_fallback.py
import time
import logging
from typing import Dict

logger = logging.getLogger("algogpt.ws_fallback")

_last_prices: Dict[str, Dict] = {}

def update_price(symbol: str, price: float):
    """
    עדכון מחיר בזיכרון (Fallback במקרה ש־WS או API נופלים).
    """
    _last_prices[symbol] = {"price": price, "ts": time.time()}
    logger.debug(f"Updated {symbol} price={price}")

def get_price(symbol: str) -> float:
    """
    מחזיר מחיר אחרון שנשמר בזיכרון או 0 אם אין.
    """
    entry = _last_prices.get(symbol)
    if not entry:
        logger.warning(f"No price found for {symbol}")
        return 0.0
    return entry["price"]

def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    """
    בודק אם המחיר האחרון של הסמול עדיין טרי (לא ישן יותר מ־max_age_sec שניות).
    """
    entry = _last_prices.get(symbol)
    if not entry:
        logger.debug(f"No entry for {symbol}, price not fresh")
        return False
    age = time.time() - entry["ts"]
    return age <= max_age_sec


















