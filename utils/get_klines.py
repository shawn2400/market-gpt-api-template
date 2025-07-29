import logging
import pandas as pd
import numpy as np
import ta
from utils.binance_client import client
import requests.exceptions

# --- פונקציה לשליפת נתוני Klines מ-Binance ---
def get_klines(
    symbol: str,
    interval: str = '15m',
    limit: int = 500,
    market_type: str = "futures",
    grid_base_type: str = "futures",
    start_time: int = None,
    end_time: int = None,
    is_futures: bool = None
) -> pd.DataFrame:
    """
    מחזיר DataFrame עם נתוני נרות (klines) מ-Binance.
    כולל טיפול בשגיאות, בדיקה וניקוי נתונים חסרים.
    """
    if is_futures is not None:
        market_type = "futures" if is_futures else "spot"

    if not client:
        logging.warning("⚠️ Binance client לא מחובר.")
        return pd.DataFrame()

    mt = market_type
    if market_type == "grid":
        mt = grid_base_type if grid_base_type in ("futures", "spot") else "futures"

    try:
        if mt == "futures":
            raw = client.futures_klines(
                symbol=symbol,
                interval=interval,
                limit=limit,
                startTime=start_time,
                endTime=end_time
            )
        elif mt == "spot":
            raw = client.get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit,
                startTime=start_time,
                endTime=end_time
            )
        else:
            logging.error(f"[!] סוג שוק לא נתמך: {mt}")
            return pd.DataFrame()

        if not raw:
            logging.warning(f"[!] נתוני Klines ריקים עבור {symbol} בשוק {mt}")
            return pd.DataFrame()

        df = pd.DataFrame(raw, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
        ])

        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)

        if df.isnull().any().any():
            logging.warning(f"[!] נתוני Klines עבור {symbol} מכילים ערכים חסרים – מסירים שורות ריקות")
            df.dropna(inplace=True)

        if len(df) < 30:
            logging.warning(f"[!] אחרי ניקוי, מעט מדי נתונים ({len(df)}) עבור {symbol} לניתוח אמין")

        return df

    except requests.exceptions.RequestException as e:
        logging.error(f"[!] שגיאת רשת בבקשת Klines עבור {symbol}: {e}")
        return pd.DataFrame()

    except Exception as e:
        logging.error(f"[!] שגיאה כללית בשליפת Klines עבור {symbol}: {type(e).__name__} – {e}")
        return pd.DataFrame()









