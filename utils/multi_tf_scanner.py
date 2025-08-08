# utils/multi_tf_scanner.py
import asyncio
import logging
from typing import List
from utils.trending_utils import get_trending_symbols
from utils.scanner_utils import analyze_symbol, semaphore
from utils.ai_analysis import analyze_with_ai
from utils.watchlist_utils import load_watchlist

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
    logging.info(
        f"[multi_tf_scanner] התחלת סריקה: "
        f"tf={timeframes}, markets={markets}, min_quality={min_quality}, top={top}, trending_only={trending_only}"
    )

    # --- שלב 1: טעינת watchlist ---
    symbols = load_watchlist(min_quality=min_quality)
    if symbols:
        logging.info(f"[multi_tf_scanner] סמלים מ-watchlist: {symbols}")
    else:
        logging.warning("[multi_tf_scanner] watchlist ריק – משתמש ב-trending API")
        try:
            symbols = await get_trending_symbols(trending_source)
        except Exception as e:
            logging.error(f"[multi_tf_scanner] שגיאה ב-get_trending_symbols: {e}")
            return []

    if not symbols:
        logging.warning("[multi_tf_scanner] אין סמלים לסריקה")
        return []

    # --- שלב 2: הגבלת מספר סמלים ---
    symbols = symbols[:MAX_SYMBOLS]

    # --- שלב 3: סריקה אסינכרונית לכל סמל ולכל טיימפריים ---
    tasks = []
    for symbol in symbols:
        for tf in timeframes:
            tasks.append(safe_analyze(symbol, tf, markets[0], trending_only))

    results_raw = await asyncio.gather(*tasks)
    results_raw = [r for r in results_raw if r]

    # --- שלב 4: קיבוץ תוצאות לפי סימבול ---
    grouped = {}
    for r in results_raw:
        sym = r["symbol"]
        if sym not in grouped:
            grouped[sym] = []
        grouped[sym].append(r)

    # --- שלב 5: עיבוד תוצאות עם AI ---
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

    # --- שלב 6: מיון והחזרת top N ---
    final_results.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    return final_results[:top]

# --- פונקציית fallback לסריקה ידנית ---
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


































