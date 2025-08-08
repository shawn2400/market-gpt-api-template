import asyncio
import logging
from typing import List
from utils.trending_utils import get_trending_symbols
from utils.scanner_utils import analyze_symbol, semaphore
from utils.ai_analysis import analyze_with_ai
from utils.watchlist_utils import load_watchlist  # חדש

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

    if trending_only:
        # שימוש ב־API ל־Trending
        symbols = get_trending_symbols(trending_source=trending_source, market_type=markets[0])
        logging.info(f"[multi_tf_scanner] סמלים טרנדיים נבחרו: {symbols}")
    else:
        # טעינת רשימת מעקב מקובץ
        watchlist = load_watchlist()
        symbols = [item["symbol"] for item in watchlist if item.get("symbol")]
        logging.info(f"[multi_tf_scanner] טעינת {len(symbols)} סמלים מ־watchlist.json")

        # fallback אם הרשימה ריקה
        if not symbols:
            logging.warning("[multi_tf_scanner] watchlist ריק — נופל ל־get_trending_symbols")
            symbols = get_trending_symbols(trending_source=trending_source, market_type=markets[0])

    if not symbols:
        logging.warning("[multi_tf_scanner] אין סמלים לסריקה")
        return []

    # הגבלת מספר סמלים
    symbols = symbols[:MAX_SYMBOLS]

    # סריקה אסינכרונית לכל סמל ולכל טיימפריים
    tasks = [safe_analyze(symbol, tf, markets[0], trending_only) for symbol in symbols for tf in timeframes]
    results_raw = await asyncio.gather(*tasks)
    results_raw = [r for r in results_raw if r]

    # קיבוץ תוצאות לפי סימבול
    grouped = {}
    for r in results_raw:
        sym = r["symbol"]
        grouped.setdefault(sym, []).append(r)

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


async def fallback_scan_manual(symbol: str) -> List[dict]:
    logging.info(f"[multi_tf_scanner] ביצוע סריקה ידנית fallback עבור {symbol}")
    try:
        result = await analyze_symbol(symbol, interval="15m", market_type="futures")
        if result:
            return [result]
        else:
            return []
    except Exception as e:
        logging.error(f"[multi_tf_scanner] ❌ שגיאה ב-fallback_scan_manual עבור {symbol}: {e}")
        return []


































