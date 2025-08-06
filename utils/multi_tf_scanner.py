# utils/multi_tf_scanner.py

import asyncio
import logging
from collections import defaultdict
from typing import Optional, Dict, List
from utils.trending_utils import get_trending_symbols
from utils.ai_analysis import analyze_with_ai
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.quality_score import calculate_quality_score

# ✅ Semaphore פנימי למניעת עומס
semaphore = asyncio.Semaphore(10)

MAX_SYMBOLS = 20
MAX_TFS = 3

# ✅ פונקציית ניתוח סימבול בודד
async def analyze_symbol(
    symbol: str,
    market_type: str = "futures",
    interval: str = "15m",
    limit: int = 100,
    trending_only: bool = True,
    with_ai: bool = False,
    frames: Optional[List[str]] = None
) -> Optional[Dict]:
    try:
        df = await get_klines(symbol, interval, market=market_type, limit=limit)
        if df is None or len(df) < 50:
            logging.warning(f"[analyze_symbol] אין מספיק נתונים ל־{symbol}")
            return None

        indicators = compute_indicators(df)
        if not indicators or indicators.get("volume", 0) < 100_000:
            return None

        direction = (
            "LONG" if indicators["macd"] > 0 and indicators["rsi"] > 50 else
            "SHORT" if indicators["macd"] < 0 and indicators["rsi"] < 50 else
            "NEUTRAL"
        )

        quality_score = calculate_quality_score(indicators)

        return {
            "symbol": symbol,
            "interval": interval,
            "direction": direction,
            "indicators": indicators,
            "quality_score": quality_score,
            "frames": frames or [interval],
            "volume": indicators.get("volume", 0),
            "pattern": indicators.get("pattern", "unknown")
        }

    except Exception as e:
        logging.error(f"[analyze_symbol] ❌ שגיאה בניתוח {symbol}@{interval}: {e}")
        return None

# ✅ ניתוח סריקה מרובה עם AI
async def safe_analyze(symbol, tf, market, trending_only):
    try:
        async with semaphore:
            return await analyze_symbol(
                symbol=symbol,
                market_type=market,
                interval=tf,
                limit=100,
                trending_only=trending_only,
                with_ai=False,
                frames=[tf]
            )
    except Exception as e:
        logging.error(f"[multi_tf_scanner] ❌ analyze_symbol נכשל עבור {symbol}@{tf}: {e}")
        return None

async def multi_tf_scan_with_ai(
    timeframes=("5m", "15m", "1h"),
    markets=("futures",),
    min_quality=6,
    top=10,
    trending_only=True,
    trending_source="coingecko"
):
    try:
        logging.info(f"[multi_tf_scanner] התחלת סריקה: tf={timeframes}, markets={markets}, min_quality={min_quality}, top={top}, trending_only={trending_only}, trending_source={trending_source}")

        symbols = set()
        for market in markets:
            try:
                syms = get_trending_symbols(trending_source=trending_source, market_type=market)
                symbols.update(syms)
            except Exception as e:
                logging.warning(f"[multi_tf_scanner] שגיאה בשליפת סימבולים ל-{market}: {e}")

        if not symbols:
            logging.warning("[multi_tf_scanner] ⚠️ לא נמצאו סימבולים לסריקה.")
            return []

        symbols = list(symbols)[:MAX_SYMBOLS]
        timeframes = list(timeframes)[:MAX_TFS]

        tasks = [
            safe_analyze(symbol, tf, markets[0], trending_only)
            for tf in timeframes
            for symbol in symbols
        ]
        raw_results = await asyncio.gather(*tasks)

        grouped = defaultdict(list)
        for result in raw_results:
            if result and isinstance(result, dict) and result.get("quality_score", 0) >= min_quality:
                grouped[result["symbol"]].append(result)

        output = []
        for symbol, entries in grouped.items():
            if len(entries) < 2:
                continue

            directions = [x["direction"] for x in entries]
            main_dir = max(set(directions), key=directions.count)

            filtered_entries = [x for x in entries if x["direction"] == main_dir]
            if not filtered_entries:
                continue

            try:
                avg_q = sum(x["quality_score"] for x in filtered_entries) / len(filtered_entries)
            except Exception as e:
                logging.error(f"[multi_tf_scanner] שגיאה בחישוב ממוצע איכות עבור {symbol}: {e}")
                continue

            try:
                last = entries[-1]
                ind = last.get("indicators") or {}

                ai_result = await analyze_with_ai(
                    symbol=symbol,
                    rsi=ind.get("rsi", 50),
                    adx=ind.get("adx", 20),
                    trend=main_dir,
                    volume=last.get("volume", 1_000_000),
                    pattern=last.get("pattern", "unknown")
                )
            except Exception as e:
                logging.error(f"[multi_tf_scanner] ❌ שגיאה ב־analyze_with_ai עבור {symbol}: {e}")
                continue

            if (
                ai_result
                and isinstance(ai_result, dict)
                and not ai_result.get("error")
                and main_dir.lower() in ai_result.get("signal", "").lower()
            ):
                output.append({
                    "symbol": symbol,
                    "confluence": len(entries),
                    "main_direction": main_dir,
                    "avg_quality": round(avg_q, 2),
                    "frames": [x["frames"][0] for x in entries],
                    "ai_opinion": ai_result.get("signal"),
                    "ai_score": ai_result.get("confidence", 1.0),
                    "details": entries
                })

        output.sort(key=lambda x: (-x["avg_quality"], -x["ai_score"]))
        return output[:top]

    except Exception as outer_e:
        logging.error(f"[multi_tf_scanner] ❌ שגיאה קריטית בכל הסריקה: {outer_e}")
        return []

# ✅ פונקציה חיצונית לשימוש מה־API
async def scan_all():
    return await multi_tf_scan_with_ai()




















