# utils/multi_tf_scanner.py

import asyncio
import logging
from collections import defaultdict
from typing import List, Tuple

from utils.trending_utils import get_trending_symbols
from utils.scanner_utils import analyze_symbol, semaphore
from utils.ai_analysis import analyze_with_ai

MAX_SYMBOLS = 20
MAX_TFS = 3

async def safe_analyze(symbol, tf, market, trending_only):
    try:
        async with semaphore:
            logging.info(f"[safe_analyze] 🚀 Start analyzing {symbol}@{tf}")
            result = await analyze_symbol(
                symbol=symbol,
                market_type=market,
                interval=tf,
                limit=120,
                trending_only=trending_only,
                with_ai=False,
                frames=[tf]
            )
            logging.info(f"[safe_analyze] ✅ Finished analyzing {symbol}@{tf}")
            return result
    except Exception as e:
        logging.error(f"[safe_analyze] ❌ analyze_symbol נכשל עבור {symbol}@{tf}: {e}")
        return None

async def multi_tf_scan_with_ai(
    timeframes: Tuple[str] = ("5m", "15m", "1h"),
    markets: Tuple[str] = ("futures",),
    min_quality: int = 6,
    top: int = 10,
    trending_only: bool = True,
    trending_source: str = "coingecko"
) -> List[dict]:
    try:
        logging.info(f"[multi_tf_scanner] ▶️ התחלת סריקה: tf={timeframes}, markets={markets}, min_quality={min_quality}, top={top}")
        results = []

        for market in markets:
            # 🔍 שליפת סמלים טרנדיים עם טיפול שגיאה
            try:
                symbols = get_trending_symbols(
                    trending_source=trending_source,
                    market_type=market,
                    top=MAX_SYMBOLS
                )
                logging.info(f"[multi_tf_scanner] ✅ {len(symbols)} סמלים נטענו מ־{trending_source} ({market})")
            except Exception as e:
                logging.error(f"[multi_tf_scanner] ❌ שגיאה ב־get_trending_symbols: {e}")
                symbols = []

            if not symbols:
                logging.warning(f"[multi_tf_scanner] ⚠️ אין סמלים לסריקה בשוק {market}")
                continue

            for symbol in symbols:
                tf_results = []

                for tf in timeframes[:MAX_TFS]:
                    result = await safe_analyze(symbol, tf, market, trending_only)
                    if result:
                        tf_results.append(result)

                if tf_results:
                    try:
                        combined_result = await analyze_with_ai(tf_results)
                        if asyncio.iscoroutine(combined_result):
                            logging.error(f"[multi_tf_scanner] ❗ analyze_with_ai החזיר coroutine! חסר await?")
                            combined_result = await combined_result

                        score = combined_result.get("quality_score", 0)
                        logging.info(f"[multi_tf_scanner] 🎯 {symbol} קיבל ציון: {score}")

                        if score >= min_quality:
                            results.append(combined_result)
                    except Exception as e:
                        logging.error(f"[multi_tf_scanner] ❌ analyze_with_ai נכשל עבור {symbol}: {e}")

        # ✅ סידור וסינון לפי ציון איכות
        sorted_results = sorted(results, key=lambda x: x.get("quality_score", 0), reverse=True)
        top_results = sorted_results[:top]

        logging.info(f"[multi_tf_scanner] 🟢 סיום סריקה: נמצאו {len(top_results)} טריידים מתאימים")
        return top_results

    except Exception as e:
        logging.exception(f"[multi_tf_scanner] ❌ שגיאה כללית: {e}")
        return []
























