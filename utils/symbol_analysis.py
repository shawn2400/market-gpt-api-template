# utils/symbol_analysis.py

from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score
from utils.static_utils import detect_pattern
from utils.get_klines import get_klines
import logging

async def analyze_symbol(symbol, market_type, interval, limit=100, trending_only=False, with_ai=False, frames=None):
    try:
        df = await get_klines(symbol, interval=interval, limit=limit, market_type=market_type)
        if df is None or len(df) < 60:
            logging.warning(f"[*] לא מספיק נרות לניתוח עבור {symbol}@{interval}")
            return None

        df = compute_indicators(df)
        last = df.iloc[-1].to_dict()
        quality = compute_quality_score(df)
        pattern = detect_pattern(df)

        return {
            "symbol": symbol,
            "frames": [interval],
            "indicators": last,
            "direction": last.get("trend", "sideways"),
            "quality_score": quality,
            "volume": last.get("volume", 0),
            "pattern": pattern,
            "trending": trending_only,
        }

    except Exception as e:
        logging.error(f"[analyze_symbol] שגיאה בניתוח {symbol}@{interval}: {e}")
        return None
