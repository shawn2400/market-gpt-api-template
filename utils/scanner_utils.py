import logging
from utils.indicators import get_klines, compute_indicators
from utils.quality_score import compute_quality_score
from utils.ai_analysis import analyze_with_ai

def get_symbols(market_type="futures"):
    from utils.binance_client import client
    if market_type == "spot":
        exchange_info = client.get_exchange_info()
        return [s['symbol'] for s in exchange_info['symbols'] if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']
    elif market_type == "futures":
        exchange_info = client.futures_exchange_info()
        return [s['symbol'] for s in exchange_info['symbols'] if s['contractType'] == 'PERPETUAL']
    else:
        return []

def analyze_symbol(
    symbol,
    interval="15m",
    market_type="futures",
    limit=120,
    with_ai=False,
    min_quality=6,
    min_volume=0,
    frames=None  # ✅ תמיכה ל-Multi-TF
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
            "frames": frames or [interval]  # ✅ תוסף תואם multi_tf_scanner
        }

    except Exception as e:
        logging.error(f"[analyze_symbol] {symbol} ❌ {e}")
        return None

def scan_all(
    market_type="futures",
    interval="15m",
    limit=120,
    top=1,
    min_quality=6,
    with_ai=False,
    min_volume=0,
    trending_only=False
):
    symbols = get_symbols(market_type)

    results = []
    for symbol in symbols:
        result = analyze_symbol(
            symbol=symbol,
            interval=interval,
            market_type=market_type,
            limit=limit,
            with_ai=with_ai,
            min_quality=min_quality,
            min_volume=min_volume
        )
        if result:
            results.append(result)

    sorted_results = sorted(results, key=lambda x: x["quality_score"], reverse=True)
    return sorted_results[:top]

























































