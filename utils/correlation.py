# utils/correlation.py
from typing import List, Dict, Any
import numpy as np
import logging
import asyncio
import aiohttp

logger = logging.getLogger("algogpt.correlation")

BINANCE_BASE = "https://api.binance.com"

async def _fetch_klines(symbol: str, interval: str, limit: int = 500) -> List[float]:
    """
    מושך מחירי סגירה מ-Binance עבור סימול מסוים.
    """
    url = f"{BINANCE_BASE}/api/v3/klines?symbol={symbol.upper()}&interval={interval}&limit={limit}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Binance API error {resp.status}: {text}")
            data = await resp.json()
            return [float(k[4]) for k in data]  # close price


async def compute_correlation(
    symbols: List[str],
    ref_symbol: str = "BTCUSDT",
    timeframe: str = "15m",
    window: int = 200
) -> List[Dict[str, Any]]:
    """
    מחשב מתאם פירסון בין כל סימול ל-BTC (או ref אחר).
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


# הרצה לבדיקה מקומית
if __name__ == "__main__":
    async def test():
        data = await compute_correlation(["ETHUSDT", "BNBUSDT"], ref_symbol="BTCUSDT", timeframe="15m", window=200)
        print(data)

    asyncio.run(test())







