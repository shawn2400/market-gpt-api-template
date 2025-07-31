import asyncio
import logging
from collections import defaultdict
from utils.trending_utils import get_trending_symbols
from utils.scanner_utils import analyze_symbol
from utils.ai_analysis import analyze_with_ai

MAX_SYMBOLS = 20
MAX_TFS = 3
SEMAPHORE = asyncio.Semaphore(10)  # הגבלת עומסים א-סינכרונית

async def multi_tf_scan_with_ai(
    timeframes=("5m", "15m", "1h"),
    markets=("futures",),
    min_quality=6,
    top=10,
    trending_only=True,
    trending_source="coingecko"
):
    logging.info(f"[multi_tf_scanner] התחלת סריקה עם פרמטרים: tf={timeframes}, markets={markets}, min_quality={min_quality}, top={top}, trending_only={trending_only}, trending_source={trending_source}")

    # 1. שליפת סימבולים
    symbols = set()
    for market in markets:
        try:
            syms = get_trending_symbols(trending_source=trending_source, market_type=market)
            symbols.update(syms)
        except Exception as e:
            logging.warning(f"[multi_tf_scanner] שגיאה בשליפת trending symbols ל-{market}: {e}")
    if not symbols:
        logging.warning("[multi_tf_scanner] לא נמצאו סימבולים טרנדיים.")
        return []

    if len(symbols) > MAX_SYMBOLS:
        logging.warning(f"[multi_tf_scanner] יותר מדי סימבולים ({len(symbols)}) – מגביל ל-{MAX_SYMBOLS}")
        symbols = list(symbols)[:MAX_SYMBOLS]

    if len(timeframes) > MAX_TFS:
        logging.warning(f"[multi_tf_scanner] יותר מדי טיימפריימים ({len(timeframes)}) – מגביל ל-{MAX_TFS}")
        timeframes = list(timeframes)[:MAX_TFS]

    # 2. בניית משימות
    tasks = []
    for tf in timeframes:
        for symbol in symbols:
            async def safe_task(symbol=symbol, tf=tf, market=markets[0]):
                try:
                    async with SEMAPHORE:
                        # נשתמש בגרסה סינכרונית של analyze_symbol מתוך thread executor
                        loop = asyncio.get_event_loop()
                        return await loop.run_in_executor(
                            None, lambda: analyze_symbol(
                                symbol=symbol,
                                interval=tf,
                                market_type=market,
                                limit=120,
                                with_ai=False,
                                min_quality=min_quality
                            )
                        )
                except Exception as e:
                    logging.error(f"[multi_tf_scanner] שגיאה ב-analyze_symbol עבור {symbol} @ {tf}: {e}")
                    return None
            tasks.append(safe_task())

    raw = await asyncio.gather(*tasks)

    # 3. עיבוד תוצאות
    results = defaultdict(list)
    for r in raw:
        if r and r.get("quality_score", 0) >= min_quality:
            r["frame"] = r.get("frame") or r.get("interval", "unknown")
            results[r["symbol"]].append(r)

    output = []
    for sym, entries in results.items():
        if len(entries) >= 2:
            directions = [x["direction"] for x in entries]
            main_dir = max(set(directions), key=directions.count)
            avg_q = sum(x["quality_score"] for x in entries if x["direction"] == main_dir) / len(entries)

            ai_data = {
                "rsi": entries[-1].get("rsi", 50),
                "adx": entries[-1].get("adx", 20),
                "trend": main_dir,
                "pattern": "unknown",
                "volume": entries[-1].get("volume", 1_000_000)
            }

            try:
                ai_res = analyze_with_ai(**ai_data)
            except Exception as e:
                logging.error(f"[multi_tf_scanner] שגיאה בניתוח AI עבור {sym}: {e}")
                ai_res = {"answer": "אין המלצה", "score": 0}

            if ai_res and main_dir.lower() in ai_res.get("answer", "").lower():
                output.append({
                    "symbol": sym,
                    "confluence": len(entries),
                    "main_direction": main_dir,
                    "avg_quality": round(avg_q, 2),
                    "frames": [x["frame"] for x in entries],
                    "ai_opinion": ai_res.get("answer"),
                    "ai_score": ai_res.get("score", 1.0),
                    "details": entries
                })

    output.sort(key=lambda x: (-x["avg_quality"], -x["ai_score"]))
    return output[:top]






