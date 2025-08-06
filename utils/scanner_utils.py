# utils/scanner_utils.py

import asyncio
import logging
from utils.quality_score import calculate_quality_score
from utils.indicators import analyze_indicators
from utils.get_klines import get_klines

# Semaphore להגבלת כמות בקשות במקביל
semaphore = asyncio.Semaphore(10)

async def analyze_symbol(symbol: str, interval: str = "15m", limit: int = 120) -> dict:
    """
    מנתח סימבול לפי אינדיקטורים ומחזיר dict עם ציון איכות, מגמה וכו'
    """
    try:
        async with semaphore:
            klines = await get_klines(symbol=symbol, interval=interval, limit=limit)
            if not klines:
                raise ValueError(f"No klines for {symbol} @ {interval}")

            indicators = analyze_indicators(klines)
            quality_score = calculate_quality_score(indicators)

            return {
                "symbol": symbol,
                "interval": interval,
                "quality_score": quality_score,
                "direction": indicators.get("trend", "LONG"),  # ברירת מחדל
                "rsi": indicators.get("rsi"),
                "adx": indicators.get("adx"),
                "volume": indicators.get("volume"),
                "market": "futures",
            }

    except Exception as e:
        logging.error(f"[scanner_utils] ❌ שגיאה בניתוח {symbol}@{interval}: {e}")
        return None

async def scan_all(interval: str = "15m", min_quality: int = 6, top: int = 10, symbols: list = None):
    """
    סריקה חכמה של רשימת סמלים עם ניתוח איכות וסינון לפי ציון.
    """
    try:
        if not symbols:
            from utils.watchlist_utils import load_watchlist
            raw_watchlist = load_watchlist()
            symbols = [x["symbol"] for x in raw_watchlist if "symbol" in x]

        if not symbols:
            logging.warning("[scanner_utils] ⚠️ אין סמלים לסריקה.")
            return []

        logging.info(f"[scanner_utils] 🔎 התחלת סריקה של {len(symbols)} סימבולים...")

        tasks = [analyze_symbol(sym, interval=interval) for sym in symbols]
        results = await asyncio.gather(*tasks)

        filtered = [r for r in results if r and r["quality_score"] >= min_quality]
        sorted_results = sorted(filtered, key=lambda x: x["quality_score"], reverse=True)

        logging.info(f"[scanner_utils] ✅ נמצאו {len(sorted_results)} טריידים מעל ציון {min_quality}")
        return sorted_results[:top]

    except Exception as e:
        logging.error(f"[scanner_utils] ❌ שגיאה בסריקה: {e}")
        return []
































































