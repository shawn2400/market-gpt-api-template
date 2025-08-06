# utils/scanner_utils.py

import asyncio
import logging
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score

semaphore = asyncio.Semaphore(10)  # מגביל ל־10 קריאות בו־זמנית

async def analyze_symbol(symbol, market_type, interval="15m", limit=100, trending_only=False, with_ai=False, frames=["15m"]):
    try:
        df = await get_klines(symbol, interval=interval, limit=limit, market_type=market_type)
        if df is None or df.empty:
            raise ValueError("אין דאטה מה־Klines")

        indicators = compute_indicators(df)
        quality = compute_quality_score(indicators)

        result = {
            "symbol": symbol,
            "interval": interval,
            "frames": frames,
            "quality_score": quality,
            "direction": indicators.get("trend", "unknown"),
            "volume": indicators.get("volume", 0),
            "pattern": indicators.get("pattern", "unknown"),
            "indicators": indicators,
        }

        logging.info(f"[analyze_symbol] {symbol}@{interval} → quality={quality:.2f}")
        return result

    except Exception as e:
        logging.warning(f"[analyze_symbol] שגיאה עבור {symbol}@{interval}: {e}")
        return None































































