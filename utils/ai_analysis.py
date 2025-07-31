from utils.binance_client import client
from binance.exceptions import BinanceAPIException, BinanceRequestException

def get_live_price(symbol: str, is_futures: bool = True) -> float:
    """
    מחזיר את המחיר החי (last price) מה־Binance API.
    """
    try:
        if is_futures:
            data = client.futures_symbol_ticker(symbol=symbol)
        else:
            data = client.get_symbol_ticker(symbol=symbol)

        return float(data["price"])

    except BinanceAPIException as e:
        print(f"[Binance API Error] {symbol}: {e}")
    except BinanceRequestException as e:
        print(f"[Binance Request Error] {symbol}: {e}")
    except Exception as e:
        print(f"[Live Price Error] {symbol}: {e}")
    
    return 0.0




















