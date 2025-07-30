# scanner_utils.py

import asyncio
import logging
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.binance_client import client
from utils.quality_score import compute_quality_score
from utils.ai_analysis import predict_optimal_sl_tp

semaphore = asyncio.Semaphore(10)  # הגבלת כמות משימות בו זמנית

def get_symbols(market_type="futures"):
    """
    מחזיר רשימת סמלים פעילים (TRADING) מ-Binance לפי סוג שוק (futures/spot).
    """
    try:
        if market_type == "futures":
            info = client.futures_exchange_info()
            symbols = [
                x['symbol'] for x in info['symbols']
                if x['quoteAsset'] == 'USDT' and x['status'] == 'TRADING'
            ]
            return symbols

        elif market_type == "spot":
            info = client.get_exchange_info()
            symbols = [
                x['symbol'] for x in info['symbols']
                if x['quoteAsset'] == 'USDT' and x['status'] == 'TRADING'
            ]
            return symbols

        else:
            raise ValueError("market_type must be 'futures' or 'spot'")

    except Exception as e:
        logging.error(f"[!] שגיאה בשליפת סמלים ({market_type}): {e}")
        # ערך ברירת מחדל במקרה של תקלה
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]

async def safe_get_klines(symbol, interval="1m", limit=50, market_type="futures"):
    """
    שולף נרות עם טיפול בשגיאות, מחזיר None במקרה של שגיאה או נתונים לא תקינים.
    """
    try:
        df = get_klines(symbol=symbol, interval=interval, limit=limit, market_type=market_type)
        if df is None or df.empty:
            logging.warning(f"[{symbol}] אין נתוני נרות (empty).")
            return None
        return df
    except Exception as e:
        logging.warning(f"[{symbol}] שגיאה בשליפת נרות: {type(e).__name__} – {e}")
        return None

async def analyze_symbol(symbol: str, market_type: str = "futures", interval: str = "1m", limit: int = 50, with_ai: bool = True):
    """
    מבצע ניתוח טכני לסימבול נתון.
    מחזיר dict עם מידע או None אם לא ניתן לנתח.
    """
    async with semaphore:
        await asyncio.sleep(0.2)  # להורדת עומס על ה-API

        df = await safe_get_klines(symbol, interval, limit, market_type)
        if df is None or len(df) < 30:
            logging.warning(f"[{symbol}] אין מספיק נתונים ({market_type}) לניתוח.")
            return None

        df = compute_indicators(df)
        if df.empty:
            logging.warning(f"[{symbol}] אין נתונים לאחר חישוב אינדיקטורים.")
            return None

        last = df.iloc[-1]

        # קביעת כיוון לפי אינדיקטורים בסיסיים
        direction = (
            "LONG" if last["rsi"] < 35 and last["adx"] > 20 and last["close"] > last["ema_21"]
            else "SHORT" if last["rsi"] > 70 and last["adx"] > 20 and last["close"] < last["ema_21"]
            else "NEUTRAL"
        )

        quality_score = compute_quality_score(df)

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

async def scan_all(market_type: str = "futures", interval: str = "1m", limit: int = 50, min_quality: int = 5, with_ai: bool = True):
    """
    סורק סמלים רבים במקביל לפי פרמטרים ומחזיר את הטובים ביותר.
    """
    symbols = get_symbols(market_type=market_type)[:limit]

    tasks = [analyze_symbol(symbol=s, market_type=market_type, interval=interval, limit=limit, with_ai=with_ai) for s in symbols]
    results = await asyncio.gather(*tasks)

    # סינון רק תוצאות תקינות עם quality_score מעל סף וכיוון LONG/SHORT בלבד
    filtered = [
        r for r in results if r and r["quality_score"] >= min_quality and r["direction"] in ("LONG", "SHORT")
    ]

    # מיון לפי quality_score ונפח
    filtered = sorted(filtered, key=lambda x: (-x["quality_score"], -x["volume"]))

    return filtered[:5]  # מחזיר עד 5 תוצאות מובילות


















































