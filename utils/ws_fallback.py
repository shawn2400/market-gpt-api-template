# utils/ws_fallback.py
import asyncio
import time
import logging
from typing import Dict, Any, Optional, List

from utils.binance_client import futures_mark_price

LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
logger = logging.getLogger("algogpt.ws")


def update_price(symbol: str, price: float) -> None:
    """עדכון מחיר טרי ב־Cache"""
    if price is None:
        return
    try:
        p = float(price)
        if p <= 0:
            return
    except Exception:
        return
    LAST_PRICE_CACHE[symbol.upper()] = {"price": p, "ts": time.time()}


def get_price(symbol: str) -> Optional[float]:
    """מחזיר מחיר עדכני אם יש"""
    item = LAST_PRICE_CACHE.get(symbol.upper())
    return float(item["price"]) if item and "price" in item else None


def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    """בודק אם המחיר ב־Cache עדיין טרי"""
    info = LAST_PRICE_CACHE.get(symbol.upper())
    return bool(info and (time.time() - info.get("ts", 0.0)) <= max_age_sec)


async def auto_price_updater(symbols: List[str], interval: int = 15, stagger: float = 0.2) -> None:
    """
    לולאת עדכון מחירים אוטומטית דרך REST premiumIndex (fallback קל־משקל).
    - interval: כל כמה שניות לסבב מלא
    - stagger: דיליי קטן בין קריאות למניעת rate-limit
    """
    symbols = [s.upper() for s in symbols if isinstance(s, str) and s.strip()]
    if not symbols:
        logger.warning({"event": "price_updater_empty_symbols"})
        return

    while True:
        start = time.time()
        for sym in symbols:
            try:
                price = futures_mark_price(sym)
                if price and price > 0:
                    prev_ts = LAST_PRICE_CACHE.get(sym, {}).get("ts")
                    age_sec = round(start - (prev_ts or start), 2) if prev_ts else None
                    update_price(sym, price)
                    logger.debug({
                        "event": "price_update",
                        "symbol": sym,
                        "price": price,
                        "age_sec": age_sec
                    })
                else:
                    # fallback אם אין מחיר חדש
                    cache_price = get_price(sym)
                    if cache_price:
                        logger.warning({
                            "event": "price_fallback_cache",
                            "symbol": sym,
                            "price": cache_price
                        })
                    else:
                        logger.error({
                            "event": "price_missing",
                            "symbol": sym
                        })

            except Exception as e:
                logger.error({
                    "event": "price_update_error",
                    "symbol": sym,
                    "error": str(e)
                })

            # ✅ stagger כדי למנוע עומס/429
            await asyncio.sleep(stagger)

        # שמירה על פרק זמן קבוע בין סבבים
        elapsed = time.time() - start
        await asyncio.sleep(max(0.0, interval - elapsed))































