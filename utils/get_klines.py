# utils/get_klines.py
import logging
import pandas as pd
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
    MIN_LIMIT = 120

    if is_futures is not None:
        market_type = "futures" if is_futures else "spot"
    if not client:
        logging.warning("⚠️ Binance client לא מחובר.")
        return pd.DataFrame()
    mt = market_type
    if mt == "grid":
        mt = grid_base_type if grid_base_type in ("futures", "spot") else "futures"
    if limit < MIN_LIMIT:
        logging.info(f"[*] limit קטן מדי ({limit}) – הוגדל ל-{MIN_LIMIT} עבור {symbol}")
        limit = MIN_LIMIT
    try:
        if mt == "futures":
            raw = client.futures_klines(symbol=symbol, interval=interval, limit=limit, startTime=start_time, endTime=end_time)
        elif mt == "spot":
            raw = client.get_klines(symbol=symbol, interval=interval, limit=limit, startTime=start_time, endTime=end_time)
        else:
            logging.error(f"[!] סוג שוק לא נתמך: {mt}")
            return pd.DataFrame()
        if not raw or len(raw) < 10:
            logging.warning(f"[!] נתוני Klines ריקים/מעטים ({len(raw) if raw else 0}) עבור {symbol} ({mt})")
            return pd.DataFrame()
        df = pd.DataFrame(raw, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
        ])
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        nan_before = df.isnull().sum().sum()
        if nan_before > 0:
            logging.warning(f"[!] {nan_before} ערכים חסרים בנתוני {symbol} – מבצע ffill/bfill")
            df = df.fillna(method='ffill').fillna(method='bfill')
        nan_after = df.isnull().sum().sum()
        if nan_after > 0:
            logging.warning(f"[!] עדיין {nan_after} NaN – הסרה סופית של שורות ריקות")
            df.dropna(inplace=True)
        if len(df) < MIN_LIMIT // 2:
            logging.warning(f"[!] אחרי ניקוי, מעט מדי נתונים ({len(df)}) עבור {symbol} ({mt})")
            return pd.DataFrame()
        logging.info(f"[get_klines] {symbol} ({interval}, {mt}): {len(df)} נרות")
        return df
    except requests.exceptions.RequestException as e:
        logging.error(f"[!] שגיאת רשת בבקשת Klines עבור {symbol}: {e}")
        return pd.DataFrame()
    except Exception as e:
        logging.error(f"[!] שגיאה בשליפת Klines עבור {symbol}: {type(e).__name__} – {e}")
        return pd.DataFrame()











