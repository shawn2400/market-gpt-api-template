import asyncio
import logging
from typing import List
from utils.trending_utils import get_trending_symbols
from utils.scanner_utils import analyze_symbol, semaphore
from utils.ai_analysis import analyze_with_ai

MAX_SYMBOLS = 20

async def safe_analyze(symbol: str, tf: str, market: str, trending_only: bool):
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
    trending_only=False,
    trending_source="coingecko"
):
    logging.info(f"[multi_tf_scanner] התחלת סריקה: tf={timeframes}, markets={markets}, min_quality={min_quality}, top={top}, trending_only={trending_only}")
    symbols = []

    # מקבל סמלים טרנדיים אם נדרש
    if trending_only:
        symbols = await get_trending_symbols(source=trending_source)
        logging.info(f"[multi_tf_scanner] סמלים טרנדיים נבחרו: {symbols}")
    else:
        # כאן מומלץ להחליף לטעינת רשימת מעקב או מקור סמלים אחר במידת הצורך
        symbols = await get_trending_symbols(source=trending_source)  # לדוגמה עדיין משתמשים בטרנדינג

    if not symbols:
        logging.warning("[multi_tf_scanner] אין סמלים לסריקה")
        return []

    # הגבלת מספר סמלים
    symbols = symbols[:MAX_SYMBOLS]

    # סריקה אסינכרונית לכל סמל ולכל טיימפריים
    tasks = []
    for symbol in symbols:
        for tf in timeframes:
            tasks.append(safe_analyze(symbol, tf, markets[0], trending_only))

    results_raw = await asyncio.gather(*tasks)
    results_raw = [r for r in results_raw if r]

    # קיבוץ תוצאות לפי סימבול
    grouped = {}
    for r in results_raw:
        sym = r["symbol"]
        if sym not in grouped:
            grouped[sym] = []
        grouped[sym].append(r)

    # עיבוד תוצאות עם AI לכל סימבול
    final_results = []
    for sym, data in grouped.items():
        avg_quality = sum(d.get("quality_score", 0) for d in data) / len(data)
        if avg_quality < min_quality:
            continue

        ai_analysis = await analyze_with_ai(data)
        if "error" in ai_analysis:
            logging.warning(f"[multi_tf_scanner] ניתוח AI נכשל עבור {sym}: {ai_analysis['error']}")
            continue

        final_results.append(ai_analysis)

    # מיון לפי ציון איכות ולקיחת top N
    final_results.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    return final_results[:top]

# פונקציה fallback לסריקה ידנית פשוטה ללא AI ומulti-TF
async def fallback_scan_manual(symbol: str) -> List[dict]:
    logging.info(f"[multi_tf_scanner] ביצוע סריקה ידנית fallback עבור {symbol}")
    try:
        # בדיקה טכנית פשוטה ב־15m בלבד, שוק פיוצ'רס
        result = await analyze_symbol(symbol, interval="15m", market_type="futures")
        if result:
            return [result]
        else:
            return []
    except Exception as e:
        logging.error(f"[multi_tf_scanner] ❌ שגיאה ב-fallback_scan_manual עבור {symbol}: {e}")
        return []
































