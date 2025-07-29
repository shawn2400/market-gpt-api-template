# utils/scanner_utils.py

import asyncio
import logging
from utils.get_klines import get_klines
from utils.indicators import compute_indicators

# סמלים נבחרים — אפשר להרחיב/לשנות
POPULAR_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT", "AVAXUSDT",
    "DOGEUSDT", "MATICUSDT", "LINKUSDT", "OPUSDT", "LTCUSDT", "DOTUSDT", "UNIUSDT",
    "FILUSDT", "SUIUSDT", "ARBUSDT", "ENAUSDT", "PEPEUSDT", "1000FLOKIUSDT"
]

def compute_quality_score(last):
    """ דירוג איכות טרייד (0–7) לפי אינדיקטורים מרכזיים """
    score = 0
    if 45 < last.get("rsi", 0) < 65: score += 1
    if last.get("adx", 0) > 20: score += 1
    if last.get("macd_hist", 0) > 0: score += 1
    if last.get("close", 0) > last.get("ema_21", 0): score += 1
    if 30 < last.get("stoch_k", 0) < 70: score += 1
    if last.get("cci", 0) > 0: score += 1
    if last.get("vwap", 0) < last.get("close", 0): score += 1
    return score

async def analyze_symbol(symbol: str, interval: str = "15m", limit: int = 100):
    """
    ניתוח סמבול בודד (כולל אינדיקטורים, כיוון טרייד, איכות)
    """
    try:
        df = get_klines(symbol=symbol, interval=interval, limit=limit)
        if df is None or len(df) < 30:
            return None
        df = compute_indicators(df)
        last = df.iloc[-1]

        direction = (
            "LONG" if last["rsi"] < 35 and last["adx"] > 20 and last["close"] > last["ema_21"]
            else "SHORT" if last["rsi"] > 70 and last["adx"] > 20 and last["close"] < last["ema_21"]
            else "NEUTRAL"
        )
        quality_score = compute_quality_score(last)

        return {
            "symbol": symbol,
            "close": float(last["close"]),
            "volume": float(last["volume"]),
            "rsi": round(float(last["rsi"]), 2),
            "adx": round(float(last["adx"]), 2),
            "macd": round(float(last["macd"]), 4),
            "macd_hist": round(float(last["macd_hist"]), 4),
            "ema_21": round(float(last["ema_21"]), 4),
            "ema_50": round(float(last["ema_50"]), 4),
            "vwap": round(float(last["vwap"]), 4),
            "bb_upper": round(float(last["bb_upper"]), 4),
            "bb_lower": round(float(last["bb_lower"]), 4),
            "stoch_k": round(float(last["stoch_k"]), 2),
            "stoch_d": round(float(last["stoch_d"]), 2),
            "obv": round(float(last["obv"]), 2),
            "cci": round(float(last["cci"]), 2),
            "mfi": round(float(last["mfi"]), 2),
            "atr": round(float(last["atr"]), 4),
            "direction": direction,
            "quality_score": int(quality_score)
        }
    except Exception as e:
        logging.warning(f"[{symbol}] analyze error: {e}")
        return None

async def scan_all_futures(symbols: list = None, interval: str = "15m", limit: int = 100, min_quality: int = 5):
    """
    סריקה חכמה לכל רשימת הסמלים, מחזירה תוצאות עם quality_score גבוה בלבד
    """
    symbols = symbols or POPULAR_SYMBOLS
    tasks = [analyze_symbol(s, interval, limit) for s in symbols]
    results = await asyncio.gather(*tasks)
    filtered = [
        r for r in results if r and r["quality_score"] >= min_quality and r["direction"] in ("LONG", "SHORT")
    ]
    # מיון לפי איכות ואז נפח
    filtered = sorted(filtered, key=lambda x: (-x["quality_score"], -x["volume"]))
    return filtered

# דוגמה לבדיקת מודול עצמאית (לא חובה לפרודקשן)
if __name__ == "__main__":
    import asyncio
    best = asyncio.run(scan_all_futures())
    for x in best:
        print(x)




































