import asyncio
import logging
from collections import defaultdict

from utils.trending_utils import get_trending_symbols
from utils.ai_analysis import analyze_with_ai
from utils.scanner_utils import analyze_symbol, semaphore

MAX_SYMBOLS = 20
MAX_TFS = 3

async def safe_analyze(symbol, tf, market, trending_only):
    try:
        async with semaphore:
            # ✅ assume analyze_symbol is סינכרונית – לכן נריץ ב־Thread Pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: analyze_symbol(
                    symbol=symbol,
                    market_type=market,
                    interval=tf,
                    limit=100,
                    trending_only=trending_only,
                    with_ai=False,
                    frames=[tf]
                )
            )
            return result
    except Exception as e:
        logging.error(f"[multi_tf_scanner] ❌ {symbol}@{tf} נכשל: {e}")
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
        logging.info(f"[multi_tf_scanner] התחלת סריקה | tf={timeframes} markets={markets} trending={trending_only}")

        symbols = set()
        for market in markets:
            try:
                syms = get_trending_symbols(trending_source, market)
                symbols.update(syms)
            except Exception as e:
                logging.warning(f"[multi_tf_scanner] שגיאה בשליפת טרנדינג: {e}")

        if not symbols:
            logging.warning("[multi_tf_scanner] ⚠️ אין סימבולים לסריקה.")
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
            if not directions:
                continue
            main_dir = max(set(directions), key=directions.count)
            filtered_entries = [x for x in entries if x["direction"] == main_dir]
            if not filtered_entries:
                continue

            try:
                avg_q = sum(x["quality_score"] for x in filtered_entries) / len(filtered_entries)
                last = entries[-1]
                ind = last.get("indicators", {})
                ai_result = await analyze_with_ai(
                    symbol=symbol,
                    rsi=ind.get("rsi", 50),
                    adx=ind.get("adx", 20),
                    trend=main_dir,
                    volume=last.get("volume", 1_000_000),
                    pattern=last.get("pattern", "unknown")
                )
            except Exception as e:
                logging.error(f"[multi_tf_scanner] שגיאה בניתוח AI עבור {symbol}: {e}")
                ai_result = {}

            if (
                ai_result and isinstance(ai_result, dict)
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
        logging.error(f"[multi_tf_scanner] ❌ שגיאה קריטית בסריקה: {outer_e}")
        return []





















