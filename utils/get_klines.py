from utils.binance_client import client
import pandas as pd

def get_klines(symbol: str, interval: str = '15m', limit: int = 100) -> pd.DataFrame:
    """
    מחזיר DataFrame של נתוני נרות (Klines) מ־Binance Futures.

    Args:
        symbol (str): סימול המטבע (כגון 'BTCUSDT')
        interval (str): טיימפריים של הנר (כגון '1m', '15m', '1h')
        limit (int): מספר נרות לשליפה (מקסימום 1500)

    Returns:
        pd.DataFrame: טבלה עם עמודות timestamp, open, high, low, close, volume
    """
    if not client:
        print("⚠️ Binance client לא מחובר.")
        return pd.DataFrame()

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
        print(f"[!] שגיאה בשליפת Klines עבור {symbol}: {e}")
        return pd.DataFrame()


