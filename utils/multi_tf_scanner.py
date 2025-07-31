# utils/multi_tf_scanner.py

import asyncio
import logging
from collections import defaultdict
from utils.trending_utils import get_trending_symbols
from utils.scanner_utils import analyze_symbol, semaphore
from utils.ai_analysis import analyze_with_ai

MAX_SYMBOLS = 20  # סימבולים מרביים לניתוח
MAX_TFS = 3       # טיימפריימים מקסימליים לסריקה

async def multi_tf_scan_with_ai(
    timeframes=("5m", "15m", "1h"),
    markets=("futures",),
    min_quality=6,
    top=10,
    trending_only=True,
    trending_source="coingecko"
):
    logging.info(f"[multi_tf_scanner] התחלת סריקה: tf={timeframes}, markets={markets}, min_quality={min_quality}, top={top}, trending_only={trending_only}, trending_source={trending_source}")

    # 1. שליפת סימבולים טרנדיים לכל מרקט
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

    # 2. הגבלת עומס סמלים וטיימפריימים
    if len(symbols) > MAX_SYMBOLS:
        logging.warning(f"[multi_tf_scanner] ⚠️ סימבולים רבים מדי ({len(symbols)}) – חותך ל-{MAX_SYMBOLS}")
    symbols = list(symbols)[:MAX_SYMBOLS]

    if len(timeframes) > MAX_TFS:
        logging.warning(f"[multi_tf_scanner] ⚠️ טיימפריימים רבים מדי ({len(timeframes)}) – חותך ל-{MAX_TFS}")
    timeframes = list(timeframes)[:MAX_TFS]

    # 3. בניית משימות אסינכרוניות
    tasks = []
    for tf in timeframes:
        for symbol in symbols:
            async def safe_analyze(symbol=symbol, tf=tf, markets=markets):
                try:
                    async with semaphore:
                        return await analyze_symbol(
                            symbol=symbol,
                            market_type=markets[0],
                            interval=tf,
                            limit=50,
                            trending_only=trending_only,
                            with_ai=False,
                            frames=[tf]
                        )
                except Exception as e:
                    logging.error(f"[multi_tf_scanner] ❌ שגיאה ב־analyze_symbol עבור {symbol}@{tf}: {e}")
                    return None
            tasks.append(safe_analyze())

    # 4. הרצת כל המשימות במקביל
    raw_results = await asyncio.gather(*tasks)
    grouped = defaultdict(list)
    for result in raw_results:
        if result and result.get("quality_score", 0) >= min_quality:
            grouped[result["symbol"]].append(result)

    # 5. קונפלואנס + ניתוח AI
    output = []
    for symbol, entries in grouped.items():
        if len(entries) < 2:
            continue  # דרושה קונפלואנס

        directions = [x["direction"] for x in entries]
        main_dir = max(set(directions), key=directions.count)
        avg_q = sum(x["quality_score"] for x in entries if x["direction"] == main_dir) / len(entries)

        # ניתוח AI
        try:
            last = entries[-1]
            ai_result = analyze_with_ai(
                rsi=last.get("rsi", 50),
                adx=last.get("adx", 20),
                trend=main_dir,
                volume=last.get("volume", 1_000_000),
                pattern="unknown"
            )
        except Exception as e:
            logging.error(f"[multi_tf_scanner] שגיאה בניתוח GPT עבור {symbol}: {e}")
            ai_result = {}

        # 6. סינון לפי AI
        if ai_result and not ai_result.get("error") and (main_dir in ai_result.get("answer", "")):
            output.append({
                "symbol": symbol,
                "confluence": len(entries),
                "main_direction": main_dir,
                "avg_quality": round(avg_q, 2),
                "frames": [x["frames"][0] for x in entries],
                "ai_opinion": ai_result.get("answer"),
                "ai_score": ai_result.get("score", 1.0),
                "details": entries
            })

    # 7. מיון לפי איכות ו־AI
    output.sort(key=lambda x: (-x["avg_quality"], -x["ai_score"]))
    return output[:top]







