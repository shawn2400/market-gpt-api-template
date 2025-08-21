import asyncio, time, logging
from typing import Dict, Any
from utils.binance_client import futures_mark_price

LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
logger = logging.getLogger("algogpt.ws")

def update_price(symbol: str, price: float) -> None:
    """עדכון מחיר טרי ב־Cache"""
    if not price:
        return
    LAST_PRICE_CACHE[symbol.upper()] = {"price": price, "ts": time.time()}

def get_price(symbol: str) -> float | None:
    """מחזיר מחיר עדכני אם יש"""
    return LAST_PRICE_CACHE.get(symbol.upper(), {}).get("price")

def is_price_fresh(symbol: str, max_age_sec: int = 10) -> bool:
    """בודק אם המחיר ב־Cache עדיין טרי"""
    info = LAST_PRICE_CACHE.get(symbol.upper())
    return bool(info and (time.time() - info.get("ts", 0)) <= max_age_sec)

async def auto_price_updater(symbols: list[str], interval: int = 15, stagger: float = 0.2):
    """
    לולאת עדכון מחירים אוטומטית
    - interval: כל כמה שניות לסבב מלא
    - stagger: דיליי קטן בין קריאות למניעת rate-limit
    """
    while True:
        now = time.time()
        for sym in symbols:
            try:
                price = futures_mark_price(sym)

                if price and price > 0:
                    prev_ts = LAST_PRICE_CACHE.get(sym.upper(), {}).get("ts")
                    age_sec = round(now - prev_ts, 2) if prev_ts else None
                    update_price(sym, price)
                    logger.info({
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

            # ✅ stagger כדי למנוע עומס
            await asyncio.sleep(stagger)

        # סבב הושלם – נחכה עד ה־interval הבא
        await asyncio.sleep(max(0, interval - (time.time() - now)))






























