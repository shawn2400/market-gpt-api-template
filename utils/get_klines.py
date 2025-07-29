# utils/get_klines.py

from utils.binance_client import client
import pandas as pd

def get_klines(
    symbol: str,
    interval: str = '15m',
    limit: int = 100,
    is_futures: bool = True,
    start_time: int = None,
    end_time: int = None
) -> pd.DataFrame:
    """
    מחזיר DataFrame של נתוני נרות (Klines) מ־Binance (Futures/Spot) כולל תמיכה בטווח תאריכים.

    Args:
        symbol (str): סימול המטבע (למשל 'BTCUSDT')
        interval (str): טיימפריים של הנר (למשל '1m', '15m', '1h')
        limit (int): מספר נרות לשליפה (מקסימום 1500)
        is_futures (bool): האם למשוך Futures (ברירת מחדל: True)
        start_time (int): זמן התחלה ב־timestamp מילישניות (אופציונלי)
        end_time (int): זמן סיום ב־timestamp מילישניות (אופציונלי)

    Returns:
        pd.DataFrame: טבלה עם עמודות timestamp, open, high, low, close, volume
    """
    if not client:
        print("⚠️ Binance client לא מחובר.")
        return pd.DataFrame()

    try:
        if is_futures:
            raw = client.futures_klines(
                symbol=symbol,
                interval=interval,
                limit=limit,
                startTime=start_time,
                endTime=end_time
            )
        else:
            raw = client.get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit,
                startTime=start_time,
                endTime=end_time
            )

        df = pd.DataFrame(raw, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
        ])

        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)

        return df

    except Exception as e:
        print(f"[!] שגיאה בשליפת Klines עבור {symbol}: {e}")
        return pd.DataFrame()




