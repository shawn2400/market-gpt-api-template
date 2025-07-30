# scanner_utils.py

import asyncio
import logging
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.binance_client import client
from utils.quality_score import compute_quality_score
from utils.ai_analysis import predict_optimal_sl_tp

semaphore = asyncio.Semaphore(8)  # עד 8 במקביל, בטוח לפי רייט לימיט

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
        # רשימה מצומצמת לגיבוי
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]

async def safe_get_klines(symbol, interval="15m", limit=200, market_type="futures"):
    """
    שליפת נרות עם טיפול בשגיאות וריקון דאטה בעייתי.
    """
    try:
        df = get_klines(symbol=symbol, interval=interval, limit=limit, market_type=market_type)
        if df is None or df.empty or len(df) < 80:
            logging.warning(f"[{symbol}] אין מספיק נתונים ({len(df) if df is not None else 0}).")
            return None
        return df
    except Exception as e:
        logging.warning(f"[{symbol}] שגיאה בשליפת נרות: {type(e).__name__} – {e}")
        return None

async def analyze_symbol(symbol, market_type="futures", interval="15m", limit=200, with_ai=True, min_quality=5):
    """
    ניתוח סימבול אחד, כולל חישוב אינדיקטורים וציוני איכות.
    """
    async with semaphore:
        await asyncio.sleep(0.1)  # השהייה קטנה להורדת עומס API

        df = await safe_get_klines(symbol, interval, limit, market_type)
        if df is None:
            return None

        df = compute_indicators(df)
        if df.empty or len(df) < 60:
            logging.warning(f"[{symbol}] אין נתונים לאחר אינדיקטורים.")
            return None

        last = df.iloc[-1]
        # לוגיקת טרייד (מקבל הרבה יותר סיגנלים — לא נוקשה מדי)
        if last.get("rsi", 0) <



















































