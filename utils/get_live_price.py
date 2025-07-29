from utils.binance_client import client

def get_price(symbol: str, market_type: str = "futures") -> float:
    """
    מחזיר את מחיר השוק החי של המטבע הנתון מ־Binance.
    """
    try:
        if market_type == "futures":
            data = client.futures_symbol_ticker(symbol=symbol)
        else:
            data = client.get_symbol_ticker(symbol=symbol)
        return float(data["price"])
    except Exception as e:
        raise RuntimeError(f"שגיאה בשליפת מחיר חי עבור {symbol}: {e}")







