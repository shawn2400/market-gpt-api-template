# utils/scan_futures.py

import asyncio
import logging
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score

def get_symbols(limit=30):
    """
    מחזיר רשימת סימבולים זמינים למסחר ב־Binance Futures (מוגבל ל־30)
    """
    from utils.binance_client import client
    try:
        info = client.futures_exchange_info()
        symbols = [
            s["symbol"] for s in info["symbols"]
            if s["contractType"] == "PERPETUAL"
            and s["quoteAsset"] == "USDT"
            and s["status"] == "TRADING"
        ]
        return symbols[:limit]
    except Exception as e:
        logging.error(f"[!] שגיאה בשליפת סמלים: {e}")
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]

async def analyze_symbol(symbol: str, interval="1m", min_quality=6) -> dict:
    """
    סורק מטבע לפי אינדיקטורים ומחזיר נתונים אם עומד בקריטריונים
    """
    try:
        await asyncio.sleep(0.2)

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
        logging.warning(f"[!] שגיאה בניתוח {symbol}: {type(e).__name__} – {e}")
        return None

async def scan_all(interval="1m", limit=30, min_quality=6):
    """
    סורק את שוק ה־Futures (על עד 30 מטבעות) ומחזיר עד 5 טריידים איכותיים בלבד
    """
    symbols = get_symbols(limit)
    tasks = [analyze_symbol(symbol, interval, min_quality) for symbol in symbols]
    results = await asyncio.gather(*tasks)
    filtered = [r for r in results if r]
    sorted_results = sorted(filtered, key=lambda x: x["quality_score"], reverse=True)[:5]
    return sorted_results














