# utils/scanner_utils.py

import asyncio
import logging
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score
from utils.ai_analysis import analyze_with_ai

semaphore = asyncio.Semaphore(5)

def analyze_symbol(
    symbol,
    interval="15m",
    market_type="futures",
    limit=120,
    trending_only=False,
    with_ai=False,
    min_quality=6,
    min_volume=0,
    frames=None
):
    try:
        df = get_klines(symbol, interval=interval, limit=limit, market_type=market_type)
        if df is None or df.empty:
            return None

        df = compute_indicators(df)
        last = df.iloc[-1]

        volume = last.get("volume", 0)
        rsi = last.get("rsi", 0)
        adx = last.get("adx", 0)
        ema21 = last.get("ema21", 0)
        close = last.get("close", 0)

        direction = "LONG" if close > ema21 and rsi > 50 and adx > 20 else "SHORT"
        pattern = last.get("pattern", "")
        trend = last.get("trend", "")

        quality = compute_quality_score(df)
        if quality < min_quality:
            return None
        if volume < min_volume:
            return None

        ai_result = {"answer": "", "score": quality}
        if with_ai:
            ai_result = analyze_with_ai(rsi, adx, trend, volume, pattern)

        if ai_result["score"] < min_quality:
            return None

        return {
            "symbol": symbol,
            "direction": direction,
            "entry": close,
            "stop": round(close * 0.975, 4) if direction == "LONG" else round(close * 1.025, 4),
            "tp": round(close * 1.05, 4) if direction == "LONG" else round(close * 0.95, 4),
            "rsi": rsi,
            "adx": adx,
            "volume": volume,
            "trend": trend,
            "pattern": pattern,
            "quality_score": ai_result["score"],
            "ai_answer": ai_result["answer"],
            "frames": frames or [interval],
            "market": market_type  # 🟢 חשוב עבור trade_executor
        }

    except Exception as e:
        logging.error(f"[analyze_symbol] ❌ {symbol} @ {interval}: {e}")
        return None


async def scan_all(
    market_type="futures",
    interval="15m",
    limit=120,
    min_quality=6,
    min_volume=0,
    trending_only=False,
    with_ai=False,
    top=3
):
    from utils.trending_utils import get_trending_symbols
    from utils.watchlist_utils import get_default_watchlist

    logging.info(f"[scan_all] 🔍 סריקה: market={market_type}, tf={interval}, quality≥{min_quality}, trending={trending_only}")

    try:
        symbols = get_trending_symbols(trending_source="coingecko", market_type=market_type) if trending_only else []
    except Exception as e:
        logging.warning(f"[scan_all] ⚠️ שגיאה בשליפת טרנדינג: {e}")
        symbols = []

    if not symbols:
        symbols = get_default_watchlist(market_type)

    results = []

    async def safe_analyze(symbol):
        try:
            async with semaphore:
                result = analyze_symbol(
                    symbol=symbol,
                    interval=interval,
                    market_type=market_type,
                    limit=limit,
                    trending_only=trending_only,
                    with_ai=with_ai,
                    min_quality=min_quality,
                    min_volume=min_volume,
                    frames=[interval]
                )
                if result:
                    results.append(result)
        except Exception as e:
            logging.error(f"[scan_all] ❌ שגיאה עבור {symbol}: {e}")

    tasks = [safe_analyze(sym) for sym in symbols]
    await asyncio.gather(*tasks)

    results.sort(key=lambda x: -x["quality_score"])
    return results[:top]



























































