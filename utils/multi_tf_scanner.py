# utils/multi_tf_scanner.py

import asyncio
import logging
from collections import defaultdict
from utils.trending_utils import get_trending_symbols
from utils.scanner_utils import analyze_symbol
from utils.semaphore_manager import semaphore
from utils.ai_analysis import analyze_with_ai

MAX_SYMBOLS = 20
MAX_TFS = 3

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

# ✅ פונקציית scan_all לשימוש מ־auto_executor או API
async def scan_all():
    return await multi_tf_scan_with_ai()



















