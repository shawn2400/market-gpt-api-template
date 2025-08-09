import logging
import asyncio
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
                limit=120,
                trending_only=trending_only,
                with_ai=False,
                frames=[tf]
            )
    except Exception as e:
        logging.error(f"[multi_tf_scanner] analyze_symbol failed for {symbol}@{tf}: {e}")
        return None

async def multi_tf_scan_with_ai(
    timeframes=("5m", "15m", "1h"),
    markets=("futures",),
    min_quality=6,
    top=10,
    trending_only=False,
    trending_source="coingecko"
):
    logging.info(f"[multi_tf_scanner] Starting scan: tf={timeframes}, markets={markets}, min_quality={min_quality}, top={top}, trending_only={trending_only}")

    symbols = []
    try:
        watchlist = load_watchlist()
        if watchlist:
            symbols = [item["symbol"] for item in watchlist]
            logging.info(f"[multi_tf_scanner] Symbols loaded from watchlist.json: {symbols}")
    except Exception as e:
        logging.warning(f"[multi_tf_scanner] Error loading watchlist.json: {e}")

    if not symbols:
        try:
            symbols = get_trending_symbols(trending_source, markets[0])
            logging.info(f"[multi_tf_scanner] Trending symbols: {symbols}")
        except Exception as e:
            logging.error(f"[multi_tf_scanner] Trending fetch error: {e}")

    if not symbols:
        symbols = FALLBACK_SYMBOLS
        logging.warning(f"[multi_tf_scanner] Using fallback symbols: {symbols}")

    symbols = symbols[:MAX_SYMBOLS]

    tasks = [safe_analyze(sym, tf, markets[0], trending_only) for sym in symbols for tf in timeframes]

    results_raw = await asyncio.gather(*tasks)
    results_raw = [r for r in results_raw if r]

    grouped = {}
    for r in results_raw:
        sym = r.get("symbol")
        if not sym:
            logging.warning(f"[multi_tf_scanner] Skipping result without symbol: {r}")
            continue
        grouped.setdefault(sym, []).append(r)

    final_results = []
    for sym, data in grouped.items():
        avg_quality = sum(d.get("quality_score", 0) for d in data) / len(data)
        if avg_quality < min_quality:
            continue

        ai_analysis = await analyze_with_ai(data)

        # בדיקות תקינות על תוצאת ה-AI:
        if not isinstance(ai_analysis, dict):
            logging.warning(f"[multi_tf_scanner] AI analysis result not dict for {sym}: {ai_analysis}")
            continue

        required_keys = {"symbol", "quality_score", "direction", "signal", "confidence"}
        if not required_keys.issubset(ai_analysis.keys()):
            logging.warning(f"[multi_tf_scanner] AI analysis missing keys for {sym}: {ai_analysis.keys()}")
            continue

        if "error" in ai_analysis:
            logging.warning(f"[multi_tf_scanner] AI analysis error for {sym}: {ai_analysis['error']}")
            continue

        final_results.append(ai_analysis)

    final_results.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    return final_results[:top]










































































