# utils/get_live_price.py

from utils.binance_client import client
from binance.exceptions import BinanceAPIException

def get_live_price(symbol: str, is_futures: bool = True) -> float:
    """
    מחזיר את מחיר השוק הנוכחי (last price) מה־Binance API.

    :param symbol: לדוגמה "BTCUSDT"
    :param is_futures: אם True – שליפה מ־Futures, אחרת מ־Spot
    :return: מחיר נוכחי כ־float או שגיאה
    """
    try:
        if is_futures:
            data = client.futures_symbol_ticker(symbol=symbol)
        else:
            data = client.get_symbol_ticker(symbol=symbol)
        price = float(data["price"])
        return price
    except BinanceAPIException as e:
        print(f"[Binance API Error] שגיאת Binance עבור {symbol}: {e}")
    except Exception as e:
        print(f"[Live Price Error] שגיאה כללית עבור {symbol}: {e}")
    return 0.0  # fallback במקרה של כשל









