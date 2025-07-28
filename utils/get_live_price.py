# utils/get_live_price.py

from utils.binance_client import client

def get_live_price(symbol, is_futures=True):
    """
    מחזיר את המחיר העדכני למטבע נתון מ־Binance.
    תומך ב־Futures או Spot לפי הצורך.
    """
    try:
        if is_futures:
            data = client.futures_symbol_ticker(symbol=symbol)
        else:
            data = client.get_symbol_ticker(symbol=symbol)
        return float(data['price'])
    except Exception as e:
        print(f"[!] שגיאה בשליפת מחיר עבור {symbol}: {e}")
        return None

