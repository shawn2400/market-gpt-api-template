from utils.binance_client import client

def get_klines(symbol, interval='15m', limit=100):
    try:
        return client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    except Exception as e:
        print(f"שגיאה בשליפת Klines עבור {symbol}: {e}")
        return []

