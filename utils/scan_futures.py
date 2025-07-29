# utils/scan_futures.py

import asyncio
import logging
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score  # ✅ אחיד
from utils.ai_analysis import analyze_with_ai  # ✅ ניתוח GPT

# סמלים נפוצים (ברירת מחדל)
POPULAR_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT",
    "XRPUSDT", "AVAXUSDT", "DOGEUSDT", "MATICUSDT", "LINKUSDT"
]


async def analyze_symbol(symbol: str, interval: str = "15m", limit: int = 100):
    try:
        df = get_klines(symbol=symbol, interval=interval, limit=limit, market_type="futures")
        if df is None or df.empty or len(df) < 30:
            logging.warning(f"[{symbol}] אין מספיק נתונים")
            return None

        df = compute_indicators(df)
        if df.empty or len(df) < 30:
            logging.warning(f"[{symbol}] אין מספיק אינדיקטורים")
            return None

        last = df.iloc[-1]

        # כיוון עסקה
        direction = (
            "LONG" if last["rsi"] < 35 and last["adx"] > 20 and last["close"] > last["ema_21"]
            else "SHORT" if last["rsi"] > 70 and last["adx"] > 20 and last["close"] < last["ema_21"]
            else "NEUTRAL"
        )

        if direction == "NEUTRAL":
            return None

        # חישוב ציון איכות
        quality = compute_quality_score(df)

        # ניתוח GPT (חכם)
        gpt_analysis = analyze_with_ai({
            "rsi": last["rsi"],
            "adx": last["adx"],
            "trend": direction,
            "volume": last["volume"],
            "pattern": "N/A"
        })
        ai_comment = gpt_analysis.get("analysis", "") if isinstance(gpt_analysis, dict) else ""

        return {
            "symbol": symbol,
            "price": float(last["close"]),
            "volume": float(last["volume"]),
            "rsi": round(float(last["rsi"]), 2),
            "adx": round(float(last["adx"]), 2),
            "macd": round(float(last["macd"]), 4),
            "macd_hist": round(float(last["macd_hist"]), 4),
            "ema_21": round(float(last["ema_21"]), 4),
            "ema_50": round(float(last["ema_50"]), 4),
            "atr": round(float(last["atr"]), 4),
            "vwap": round(float(last["vwap"]), 4),
            "stoch_k": round(float(last["stoch_k"]), 2),
            "obv": round(float(last["obv"]), 2),
            "mfi": round(float(last["mfi"]), 2),
            "cci": round(float(last["cci"]), 2),
            "bb_upper": round(float(last["bb_upper"]), 4),
            "bb_lower": round(float(last["bb_lower"]), 4),
            "direction": direction,
            "quality_score": quality,
            "ai_analysis": ai_comment
        }

    except Exception as e:
        logging.warning(f"[{symbol}] analyze error: {e}")
        return None


async def scan_all(symbols: list = None, interval: str = "15m", limit: int = 100, min_quality: int = 5):
    if symbols is None:
        symbols = POPULAR_SYMBOLS

    tasks = [analyze_symbol(s, interval, limit) for s in symbols]
    results = await asyncio.gather(*tasks)

    filtered = [
        r for r in results
        if r and r["quality_score"] >= min_quality and r["direction"] in ("LONG", "SHORT")
    ]

    return sorted(filtered, key=lambda x: (-x["quality_score"], -x["volume"]))














