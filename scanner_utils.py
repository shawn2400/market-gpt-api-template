# scanner_utils.py

import logging
from utils.binance_client import client  # מניח שיש client מוכן מראש
from utils.get_klines import get_klines  # פונקציה לשליפת נרות

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
        # ערך ברירת מחדל אם יש תקלה
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]

async def safe_get_klines(symbol, interval="1m", limit=50, market_type="futures"):
    """
    שולף נרות עם טיפול בשגיאות, מחזיר None במקרה של שגיאה.
    """
    try:
        df = get_klines(symbol=symbol, interval=interval, limit=limit, market_type=market_type)
        if df is None or df.empty:
            return None
        return df
    except Exception as e:
        logging.warning(f"[{symbol}] שגיאה בשליפת נרות: {e}")
        return None

# דוגמה לשימוש בקריאת קווים בתוך הפונקציה scan_all למשל:

import asyncio

async def analyze_symbol(symbol: str, market_type: str = "futures", interval: str = "1m", limit: int = 50):
    df = await safe_get_klines(symbol, interval, limit, market_type)
    if df is None:
        return None
    # המשך עיבוד עם df תקין


















































