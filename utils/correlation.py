# utils/correlation.py
from typing import List, Dict, Any
import numpy as np
import logging
import asyncio
import aiohttp
import time
import os

logger = logging.getLogger("algogpt.correlation")

BINANCE_BASE = "https://api.binance.com"
CACHE_TTL = 60  # ברירת מחדל – 60 שניות

# --- Redis או fallback ל־in-memory ---
_redis = None
try:
    import redis.asyncio as redis
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        _redis = redis.from_url(redis_url, decode_responses=True)
        logger.info(f"[CORR] Using Redis cache at {redis_url}")
    else:
        logger.info("[CORR] No REDIS_URL – fallback to in-memory cache")
except Exception as e:
    logger.warning(f"[CORR] Redis not available: {e} → fallback to memory")
    _redis = None

# --- fallback memory cache ---
_cache: dict[tuple[str, str, int], tuple[float, List[float]]] = {}


async def _fetch_klines(symbol: str, interval: str, limit: int = 500) -> List[float]:
    """
    מושך מחירי סגירה מ-Binance עם Cache (Redis או memory).
    """
    key = f"klines:{symbol.upper()}:{interval}:{limit}"
    now = time.time()

    # --- Redis cache ---
    if _redis:
        try:
            data = await _redis.get(key)
            if data:
                ts, prices_str = data.split("|", 1)
                if now - float(ts) < CACHE_TTL:
                    prices = [float(x) for x in prices_str.split(",")]
                    logger.debug(f"[CACHE][Redis] hit {symbol} {interval} {limit}")
                    return prices
        except Exception as e:
            logger.warning(f"[CACHE][Redis] error {e} – fallback to API")

    # --- Memory cache ---
    if not _redis and key in _cache:
        ts, prices = _cache[key]
        if now - ts < CACHE_TTL:
            logger.debug(f"[CACHE][Mem] hit {symbol} {interval} {limit}")
            return prices
        else:
            _cache.pop(key, None)

    # --- Fetch from Binance ---
    url = f"{BINANCE_BASE}/api/v3/klines?symbol={symbol.upper()}&interval={interval}&limit={limit}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Binance API error {resp.status}: {text}")
            data = await resp.json()
            closes = [float(k[4]) for k in data]

    # --- Save to cache ---
    if _redis:
        try:
            await _redis.set(key, f"{now}|{','.join(map(str, closes))}", ex=CACHE_TTL)
        except Exception as e:
            logger.warning(f"[CACHE][Redis] save error: {e}")
    else:
        _cache[key] = (now, closes)

    return closes


async def compute_correlation(
    symbols: List[str],
    ref_symbol: str = "BTCUSDT",
    timeframe: str = "15m",
    window: int = 200
) -> List[Dict[str, Any]]:
    """
    מחשב מתאם פירסון בין כל סימול ל־BTC (או ref אחר), כולל Cache (Redis או Mem).
    """
    results: List[Dict[str, Any]] = []

    try:
        ref_prices = await _fetch_klines(ref_symbol, timeframe, limit=window)
    except Exception as e:
        logger.error(f"Failed to fetch reference {ref_symbol}: {e}")
        return [{"symbol": ref_symbol, "error": str(e)}]

    for sym in symbols:
        try:
            prices = await _fetch_klines(sym, timeframe, limit=window)
            if len(prices) != len(ref_prices):
                logger.warning(f"Symbol {sym} has mismatched data length vs {ref_symbol}")
                corr = float("nan")
            else:
                corr = float(np.corrcoef(prices, ref_prices)[0, 1])

            results.append({
                "symbol": sym,
                "ref": ref_symbol,
                "timeframe": timeframe,
                "window": window,
                "correlation": corr
            })
        except Exception as e:
            logger.error(f"Failed correlation calc for {sym}: {e}")
            results.append({
                "symbol": sym,
                "ref": ref_symbol,
                "error": str(e)
            })

    return results


# --- בדיקה ידנית ---
if __name__ == "__main__":
    async def test():
        data = await compute_correlation(["ETHUSDT", "BNBUSDT"], ref_symbol="BTCUSDT")
        print("First call:", data)
        # שנייה – אמורה להיכנס ל־Cache
        data2 = await compute_correlation(["ETHUSDT", "BNBUSDT"], ref_symbol="BTCUSDT")
        print("Second call (cache):", data2)

    asyncio.run(test())








