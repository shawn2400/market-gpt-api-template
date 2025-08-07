import asyncio
import logging

from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score

# Semaphore להגבלת מקביליות
semaphore = asyncio.Semaphore(5)

async def analyze_symbol(
    symbol: str,
    interval: str = "15m",
    market_type: str = "futures",
    limit: int = 150,
    trending_only: bool = False,
    with_ai: bool = False,
    frames: list = None
) -> dict:
    """
    מבצע ניתוח טכני מלא לסימבול ומחזיר טרייד עם איכות וניתוח.
    """
    try:
        async with semaphore:
            df = get_klines(symbol=symbol, interval=interval, limit=limit, market_type=market_type)
            if df is None or df.empty:
                logging.warning(f"[analyze_symbol] ⚠️ אין נתונים עבור {symbol}")
                return None

            df = compute_indicators(df)
            if df.empty or "rsi" not in df.columns or "adx" not in df.columns or "supertrend_dir" not in df.columns:
                logging.warning(f"[analyze_symbol] ⚠️ אינדיקטורים חסרים עבור {symbol}")
                return None

            score = compute_quality_score(df)

            return {
                "symbol": symbol,
                "interval": interval,
                "quality_score": score,
                "rsi": round(df["rsi"].iloc[-1], 2),
                "adx": round(df["adx"].iloc[-1], 2),
                "trend": "UP" if df["supertrend_dir"].iloc[-1] == 1 else "DOWN",
                "direction": "LONG" if df["supertrend_dir"].iloc[-1] == 1 else "SHORT",
                "volume": round(df["volume"].iloc[-1], 2),
                "market": market_type,
                "frames": frames or [],
                "indicators": {
                    "rsi": round(df["rsi"].iloc[-1], 2),
                    "adx": round(df["adx"].iloc[-1], 2),
                    "pattern": df["pattern"].iloc[-1] if "pattern" in df.columns else "unknown"
                }
            }

    except Exception as e:
        logging.error(f"[analyze_symbol] ❌ שגיאה בניתוח {symbol}: {e}")
        return None


async def scan_all(
    interval: str = "15m",
    min_quality: int = 6,
    top: int = 10,
    symbols: list = None,
    market_type: str = "futures"
):
    """
    מבצע סריקה לכל הסימבולים לפי ניתוח טכני ומחזיר את ה־top באיכות.
    """
    from utils.watchlist_utils import load_watchlist

    try:
        if not symbols:
            raw_watchlist = load_watchlist()
            symbols = [x["symbol"] for x in raw_watchlist if "symbol" in x]

        if not symbols:
            logging.warning("[scan_all] ⚠️ אין סמלים לסריקה.")
            return []

        logging.info(f"[scan_all] 🚀 סורק {len(symbols)} סמלים ({market_type})...")

        tasks = [
            analyze_symbol(symbol=sym, interval=interval, market_type=market_type)
            for sym in symbols
        ]

        results = await asyncio.gather(*tasks, return_exceptions=False)
        filtered = [r for r in results if r and r.get("quality_score", 0) >= min_quality]
        sorted_results = sorted(filtered, key=lambda x: x["quality_score"], reverse=True)

        logging.info(f"[scan_all] ✅ נמצאו {len(sorted_results)} טריידים מעל ציון {min_quality}")
        return sorted_results[:top]

    except Exception as e:
        logging.error(f"[scan_all] ❌ שגיאה בסריקה: {e}")
        return []

































































