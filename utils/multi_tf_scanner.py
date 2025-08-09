import asyncio
import logging
from typing import List, Optional
from utils.trending_utils import get_trending_symbols
from utils.watchlist_utils import load_watchlist
from utils.scanner_utils import analyze_symbol, semaphore
from utils.ai_analysis import analyze_with_ai

MAX_SYMBOLS = 20
FALLBACK_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

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

    # 1️⃣ ניסיון ראשון – טעינת watchlist.json
    symbols = []
    try:
        watchlist = load_watchlist()
        if watchlist:
            symbols = [item["symbol"] for item in watchlist if isinstance(item, dict) and "symbol" in item]
            logging.info(f"[multi_tf_scanner] סמלים נטענו מ־watchlist.json: {symbols}")
    except Exception as e:
        logging.warning(f"[multi_tf_scanner] שגיאה בטעינת watchlist.json: {e}")

    # 2️⃣ ניסיון שני – trending API
    if not symbols:
        try:
            symbols = get_trending_symbols(trending_source, markets[0])
            logging.info(f"[multi_tf_scanner] סמלים מטרנדינג: {symbols}")
        except Exception as e:
            logging.error(f"[multi_tf_scanner] שגיאה בקבלת סמלים מטרנדינג: {e}")

    # 3️⃣ ניסיון שלישי – fallback קבוע
    if not symbols:
        symbols = FALLBACK_SYMBOLS
        logging.warning(f"[multi_tf_scanner] שימוש ב־fallback: {symbols}")

    # הגבלת מספר סמלים
    symbols = symbols[:MAX_SYMBOLS]

    # סריקה אסינכרונית
    tasks = []
    for symbol in symbols:
        for tf in timeframes:
            tasks.append(safe_analyze(symbol, tf, markets[0], trending_only))

    results_raw = await asyncio.gather(*tasks)
    results_raw = [r for r in results_raw if r and isinstance(r, dict)]

    # קיבוץ תוצאות לפי סמל
    grouped = {}
    for r in results_raw:
        sym = r.get("symbol")
        if not sym:
            logging.warning(f"[multi_tf_scanner] תוצאה חסרה מפתח 'symbol': {r}")
            continue
        if sym not in grouped:
            grouped[sym] = []
        grouped[sym].append(r)

    # ניתוח AI לכל סמל
    final_results = []
    for sym, data in grouped.items():
        avg_quality = sum(d.get("quality_score", 0) for d in data) / len(data)
        if avg_quality < min_quality:
            continue

        ai_analysis = await analyze_with_ai(data)
        if not isinstance(ai_analysis, dict):
            logging.warning(f"[multi_tf_scanner] ניתוח AI החזיר תוצאה לא תקינה עבור {sym}: {ai_analysis}")
            continue
        if "error" in ai_analysis:
            logging.warning(f"[multi_tf_scanner] ניתוח AI נכשל עבור {sym}: {ai_analysis['error']}")
            continue

        final_results.append(ai_analysis)

    final_results.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    logging.debug(f"[multi_tf_scanner] סיום סריקה: מצא {len(final_results)} תוצאות מתאימות")
    return final_results[:top]

async def fallback_scan_manual(symbol: str):
    """
    פונקציה לעבודה ידנית עם סמל יחיד.
    מפעילה סריקה עם פרמטרים מוגדרים מראש רק עבור אותו סמל.
    """
    logging.info(f"[multi_tf_scanner] fallback_scan_manual ל־symbol: {symbol}")
    results = await multi_tf_scan_with_ai(
        timeframes=("5m", "15m", "1h"),
        markets=("futures",),
        min_quality=0,
        top=20,
        trending_only=False
    )
    filtered = [r for r in results if isinstance(r, dict) and r.get("symbol") == symbol.upper()]
    return filtered







































































