from utils.binance_client import client

def get_live_price(symbol: str, is_futures: bool = True) -> float | None:
    """
    מחזיר את המחיר העדכני למטבע נתון מ־Binance.
    
    Args:
        symbol (str): סימול המטבע (למשל "BTCUSDT")
        is_futures (bool): אם True – Futures, אחרת Spot

    Returns:
        float | None: מחיר נוכחי או None במקרה של כשל
    """
    if not client:
        print("⚠️ Binance client לא מחובר.")
        return None

    try:
        if is_futures:
            data = client.futures_symbol_ticker(symbol=symbol)
        else:
            data = client.get_symbol_ticker(symbol=symbol)
        return float(data["price"])
    except Exception as e:
        print(f"[!] שגיאה בשליפת מחיר עבור {symbol}: {e}")
        return None



