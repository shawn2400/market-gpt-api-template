# utils/scan_futures.py

import asyncio
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score

SYMBOL_LIMIT = 300

def get_symbols(limit=SYMBOL_LIMIT):
    """
    מחזיר רשימת סימבולים זמינים למסחר ב־Binance Futures
    """
    from utils.binance_client import client
    info = client.futures_exchange_info()
    symbols = [
        s["symbol"] for s in info["symbols"]
        if s["contractType"] == "PERPETUAL"
        and s["quoteAsset"] == "USDT"
        and s["status"] == "TRADING"
    ]
    return symbols[:limit]

async def analyze_symbol(symbol: str, interval="1m", min_quality=6) -> dict:
    """
    סורק מטבע לפי אינדיקטורים ומחזיר נתונים אם עומד בקריטריונים
    """
    try:
        df = get_klines(symbol=symbol, interval=interval, limit=100)
        if df is None or df.empty:
            return None

        df = compute_indicators(df)

        if df is None or df.empty:
            return None

        last = df.iloc[-1]
        score = compute_quality_score(df)

        direction = None
        if last["rsi"] < 35 and last["adx"] > 17 and last["ema21"] > last["ema50"]:
            direction = "LONG"
        elif last["rsi"] > 65 and last["adx"] > 17 and last["ema21"] < last["ema50"]:
            direction = "SHORT"

        if not direction or score < min_quality:
            return None

        return {
            "symbol": symbol,
            "rsi": round(last["rsi"], 2),
            "adx": round(last["adx"], 2),
            "macd": round(last["macd"], 4),
            "ema21": round(last["ema21"], 4),
            "ema50": round(last["ema50"], 4),
            "volume": round(last["volume"], 2),
            "quality_score": score,
            "direction": direction
        }

    except Exception as e:
        print(f"[!] שגיאה בניתוח {symbol}: {e}")
        return None

async def scan_all_futures(interval="1m", limit=SYMBOL_LIMIT, min_quality=6):
    """
    סורק את שוק ה־Futures ומחזיר את כל המטבעות שעומדים בקריטריונים
    """
    symbols = get_symbols(limit)
    tasks = [analyze_symbol(symbol, interval, min_quality) for symbol in symbols]
    results = await asyncio.gather(*tasks)
    filtered = [r for r in results if r]
    sorted_results = sorted(filtered, key=lambda x: x["quality_score"], reverse=True)
    return sorted_results












