# utils/klines_utils.py (אם תרצה לקרוא לו בשם מדויק)
from utils.binance_client import client
import pandas as pd

def get_klines(symbol, interval='15m', limit=100):
    try:
        raw = client.futures_klines(symbol=symbol, interval=interval, limit=limit)

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
        print(f"שגיאה בשליפת Klines עבור {symbol}: {e}")
        return pd.DataFrame()


