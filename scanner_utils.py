import asyncio
import logging
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.binance_client import client
from utils.quality_score import compute_quality_score
from utils.ai_analysis import predict_optimal_sl_tp


semaphore = asyncio.Semaphore(10)  # הגבלת כמות משימות בו זמנית


def get_symbols(market_type="futures"):
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
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]


def compute_quality_score(last):
    score = 0
    if 45 < last.get("rsi", 0) < 65: score += 1
    if last.get("adx", 0) > 20: score += 1
    if last.get("macd_hist", 0) > 0: score += 1
    if last.get("close", 0) > last.get("ema_21", 0): score += 1
    if 30 < last.get("stoch_k", 0) < 70: score += 1
    if last.get("cci", 0) > 0: score += 1
    if last.get("vwap", 0) < last.get("close", 0): score += 1
    return score


async def analyze_symbol(symbol: str, market_type: str = "futures", interval: str = "1m", limit: int = 50, with_ai: bool = True):
    try:
        await asyncio.sleep(0.2)

        df = get_klines(symbol=symbol, interval=interval, limit=limit, market_type=market_type)
        if df is None or df.empty or len(df) < 30:
            logging.warning(f"[{symbol}] אין מספיק נתונים ({market_type}) לניתוח")
            return None

        df = compute_indicators(df)
        if df.empty or len(df) < 1:
            logging.warning(f"[{symbol}] אין נתונים לאחר חישוב אינדיקטורים")
            return None

        last = df.iloc[-1]

        direction = (
            "LONG" if last["rsi"] < 35 and last["adx"] > 20 and last["close"] > last["ema_21"]
            else "SHORT" if last["rsi"] > 70 and last["adx"] > 20 and last["close"] < last["ema_21"]
            else "NEUTRAL"
        )
        quality_score = compute_quality_score(last)

        if direction == "NEUTRAL":
            return None

        sltp = predict_optimal_sl_tp(symbol, last["close"], direction) if with_ai else {"sl": None, "tp": None}

        return {
            "symbol": symbol,
            "market_type": market_type,
            "close": float(last["close"]),
            "volume": float(last["volume"]),
            "direction": direction,
            "quality_score": int(quality_score),
            "sl": sltp.get("sl"),
            "tp": sltp.get("tp")
        }
    except Exception as e:
        logging.warning(f"[{symbol}] analyze error ({market_type}): {type(e).__name__} – {e}")
        return None


async def scan_all(
    market_type: str = "futures",
    interval: str = "1m",
    limit: int = 50,
    min_quality: int = 5,
    with_ai: bool = True
):
    symbols = get_symbols(market_type=market_type)[:limit]

    async def safe_analyze(s):
        async with semaphore:
            return await analyze_symbol(s, market_type, interval, limit=50, with_ai=with_ai)

    tasks = [safe_analyze(s) for s in symbols]
    results = await asyncio.gather(*tasks)
    filtered = [
        r for r in results if r and r["quality_score"] >= min_quality and r["direction"] in ("LONG", "SHORT")
    ]
    filtered = sorted(filtered, key=lambda x: (-x["quality_score"], -x["volume"]))[:5]
    return filtered
















































