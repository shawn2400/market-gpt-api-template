import logging
from utils.binance_client import client

def get_live_price(symbol: str, is_futures: bool = True, source: str = "last") -> float | None:
    """
    מחזיר את המחיר העדכני של מטבע מ־Binance לפי המקור המבוקש.

    Args:
        symbol (str): סימול המטבע (למשל "BTCUSDT")
        is_futures (bool): True אם מדובר בפיוצ'רס, אחרת Spot
        source (str): מקור המחיר – 'last', 'mark', או 'index'

    Returns:
        float | None: המחיר הנוכחי או None במקרה של שגיאה
    """
    if not client:
        logging.warning("⚠️ Binance client לא מחובר.")
        return None

    try:
        if is_futures:
            if source == "mark":
                data = client.futures_mark_price(symbol=symbol)
                return float(data["markPrice"])
            elif source == "index":
                data = client.futures_index_price(symbol=symbol)
                return float(data["indexPrice"])
            else:  # default: 'last'
                data = client.futures_symbol_ticker(symbol=symbol)
                return float(data["price"])
        else:
            data = client.get_symbol_ticker(symbol=symbol)
            return float(data["price"])
    except Exception as e:
        logging.error(f"[!] שגיאה בשליפת מחיר עבור {symbol} (source={source}): {e}")
        return None



