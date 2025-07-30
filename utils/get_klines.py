import logging
import pandas as pd
import numpy as np
import ta
from utils.binance_client import client
import requests.exceptions

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
    משדרג אוטומטית limit אם צריך לניתוח אמין.
    """
    # הגדרת מינימום נתונים לניתוח אינדיקטורים
    MIN_REQUIRED = 120

    if is_futures is not None:
        market_type = "futures" if is_futures else "spot"

    if not client:
        logging.warning("⚠️ Binance client לא מחובר.")
        return pd.DataFrame()

    mt = market_type
    if market_type == "grid":
        mt = grid_base_type if grid_base_type in ("futures", "spot") else "futures"

    # מוודא limit מספיק גדול
    if limit < MIN_REQUIRED:
        logging.warning(f"[*] limit הוגדל אוטומטית ל-{MIN_REQUIRED} לניתוח תקין ({symbol}, {interval})")
        limit = MIN_REQUIRED

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

        if not raw or len(raw) < 10:
            logging.warning(f"[!] נתוני Klines ריקים או מעטים ({len(raw) if raw else 0}) עבור {symbol} ({mt})")
            return pd.DataFrame()

        # בונה DataFrame
        df = pd.DataFrame(raw, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
        ])
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        # מנקה ערכים חסרים
        nan_before = df.isnull().sum().sum()
        if nan_before > 0:
            logging.warning(f"[!] נתוני Klines עבור {symbol} מכילים {nan_before} ערכים חסרים – מבצע ffill/bfill")
            df = df.fillna(method='ffill').fillna(method='bfill')
        # בודק שוב אם יש Nan (סופי)
        nan_after = df.isnull().sum().sum()
        if nan_after > 0:
            logging.warning(f"[!] אחרי ניקוי, עדיין {nan_after} ערכים חסרים – מסיר שורות ריקות")
            df.dropna(inplace=True)

        # מסנן אם נשארו מעט מדי נרות
        if len(df) < MIN_REQUIRED // 2:
            logging.warning(f"[!] אחרי ניקוי, מעט מדי נתונים ({len(df)}) עבור {symbol} לניתוח אמין")
            return pd.DataFrame()

        # מדפיס דיאגנוסטיקה
        logging.info(f"[get_klines] {symbol} ({interval}, {mt}): {len(df)} נרות אחרונים נטו")
        return df

    except requests.exceptions.RequestException as e:
        logging.error(f"[!] שגיאת רשת בבקשת Klines עבור {symbol}: {e}")
        return pd.DataFrame()

    except Exception as e:
        logging.error(f"[!] שגיאה כללית בשליפת Klines עבור {symbol}: {type(e).__name__} – {e}")
        return pd.DataFrame()









