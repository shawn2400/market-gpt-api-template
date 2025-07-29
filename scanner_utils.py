import asyncio
import logging
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.binance_client import client

def get_symbols(market_type="futures"):
    """
    שליפת סמלים דינמית: Futures או Spot
    """
    try:
        if market_type == "futures":
            info = client.futures_exchange_info()
            return [x['symbol'] for x in info['symbols'] if x['quoteAsset'] == 'USDT']
        elif market_type == "spot":
            info = client.get_exchange_info()
            return [x['symbol'] for x in info['symbols'] if x['quoteAsset'] == 'USDT']
        else:
            raise ValueError("market_type must be 'futures' or 'spot'")
    except Exception as e:
        logging.error(f"[!] שגיאה בשליפת סמלים ({market_type}): {e}")
        # ברירת מחדל – מצומצמת
        return [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"
        ]

def compute_quality_score(last):
    """דירוג איכות טרייד (0–7) לפי אינדיקטורים מרכזיים"""
    score = 0
    if 45 < last.get("rsi", 0) < 65: score += 1
    if last.get("adx", 0) > 20: score += 1
    if last.get("macd_hist", 0) > 0: score += 1
    if last.get("close", 0) > last.get("ema_21", 0): score += 1
    if 30 < last.get("stoch_k", 0) < 70: score += 1
    if last.get("cci", 0) > 0: score += 1
    if last.get("vwap", 0) < last.get("close", 0): score += 1
    return score

async def analyze_symbol(symbol: str, market_type: str = "futures", interval: str = "15m", limit: int = 100):
    """
    ניתוח סמבול בודד (כולל אינדיקטורים, כיוון טרייד, איכות) – תומך FUTURES/SPOT
    """
    try:
        df = get_klines(symbol=symbol, interval=interval, limit=limit, market_type=market_type)
        if df is None or df.empty or len(df) < 30:
            logging.warning(f"[{symbol}] אין מספיק נתונים ({market_type}) לניתוח")
            return None
        
        df = compute_indicators(df)
        if df.empty or len(df) < 30:
            logging.warning(f"[{symbol}] DataFrame אחרי חישוב אינדיקטורים ריק או קצר מדי")
            return None
        
        last = df.iloc[-1]

        direction = (
            "LONG" if last["rsi"] < 35 and last["adx"] > 20 and last["close"] > last["ema_21"]
            else "SHORT" if last["rsi"] > 70 and last["adx"] > 20 and last["close"] < last["ema_21"]
            else "NEUTRAL"
        )
        quality_score = compute_quality_score(last)

        return {
            "symbol": symbol,
            "market_type": market_type,
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
        logging.warning(f"[{symbol}] analyze error ({market_type}): {e}")
        return None

async def scan_all(
    market_type: str = "futures",
    interval: str = "15m",
    limit: int = 100,
    min_quality: int = 5
):
    """
    סריקה חכמה לכל רשימת הסמלים ב־FUTURES/SPOT, מחזירה רק איכותיים
    """
    symbols = get_symbols(market_type=market_type)[:limit]
    tasks = [analyze_symbol(s, market_type, interval, limit) for s in symbols]
    results = await asyncio.gather(*tasks)
    filtered = [
        r for r in results if r and r["quality_score"] >= min_quality and r["direction"] in ("LONG", "SHORT")
    ]
    # מיון לפי איכות ואז נפח
    filtered = sorted(filtered, key=lambda x: (-x["quality_score"], -x["volume"]))
    return filtered

# דוגמה לשימוש – FUTURES/SPOT
if __name__ == "__main__":
    import asyncio
    print("=== FUTURES ===")
    best_futures = asyncio.run(scan_all(market_type="futures", limit=10, min_quality=2))
    for x in best_futures:
        print(x)

    print("\n=== SPOT ===")
    best_spot = asyncio.run(scan_all(market_type="spot", limit=10, min_quality=2))
    for x in best_spot:
        print(x)







































