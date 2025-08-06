# utils/scanner_utils.py

import logging
import asyncio
import pandas as pd
from typing import List, Optional

from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score
from utils.ws_fallback import get_price  # ✅ WS + fallback

# הגבלה על מקביליות
semaphore = asyncio.Semaphore(10)

async def analyze_symbol(
    symbol: str,
    market_type: str = "futures",
    interval: str = "15m",
    limit: int = 100,
    trending_only: bool = False,
    with_ai: bool = False,
    frames: Optional[List[str]] = None
) -> Optional[dict]:
    try:
        df = await get_klines(symbol, interval=interval, limit=limit, market_type=market_type)  # ✅ תיקון await
        if df.empty or len(df) < 50:
            logging.warning(f"[scanner_utils] ⚠️ No data for {symbol} ({interval})")
            return None

        df = compute_indicators(df)
        latest = df.iloc[-1]

        rsi = latest.get("rsi", 0)
        macd = latest.get("macd", 0)
        signal = latest.get("macd_signal", 0)
        adx = latest.get("adx", 0)
        volume = latest.get("volume", 0)
        ema21 = latest.get("ema21", latest.get("close"))
        close = latest.get("close")

        if close is None or close == 0:
            logging.warning(f"[scanner_utils] ⚠️ מחיר סגירה לא תקין עבור {symbol}")
            return None

        direction = None
        if rsi > 50 and macd > signal and adx > 20 and close > ema21:
            direction = "LONG"
        elif rsi < 50 and macd < signal and adx > 20 and close < ema21:
            direction = "SHORT"
        else:
            return None  # ✅ לא נמצא תנאי כניסה ברור

        quality_score = compute_quality_score(df)

        return {
            "symbol": symbol,
            "interval": interval,
            "direction": direction,
            "quality_score": round(quality_score, 2),
            "rsi": round(rsi, 2),
            "macd": round(macd, 4),
            "adx": round(adx, 2),
            "volume": volume,
            "price": close,
            "frames": frames or [interval],
            "market": market_type,
        }

    except Exception as e:
        logging.error(f"[scanner_utils] ❌ Error analyzing {symbol} ({interval}): {e}")
        return None

async def scan_all(
    symbols: List[str],
    market_type: str = "futures",
    interval: str = "15m",
    min_quality: int = 6,
    top: int = 5
) -> List[dict]:
    logging.info(f"[scanner_utils] 🔍 סריקה של {len(symbols)} סמלים ב־{interval}...")

    async def safe_analyze_wrapper(symbol: str):
        async with semaphore:
            return await analyze_symbol(symbol, market_type, interval)

    tasks = [safe_analyze_wrapper(symbol) for symbol in symbols]
    results = await asyncio.gather(*tasks)

    filtered = [res for res in results if res and res["quality_score"] >= min_quality]
    filtered.sort(key=lambda x: -x["quality_score"])

    logging.info(f"[scanner_utils] ✅ נמצאו {len(filtered)} טריידים איכותיים.")
    return filtered[:top]





























































