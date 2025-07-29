# utils/get_live_price.py

import logging

def get_live_price(symbol: str, is_futures: bool = True, source: str = "last") -> float | None:
    """
    מחזיר את המחיר העדכני של מטבע מ־Binance לפי המקור המבוקש.

    Args:
        symbol (str): לדוג' "BTCUSDT"
        is_futures (bool): True = פיוצ'רס, False = ספוט
        source (str): 'last'/'mark'/'index' (לפי פיוצ'רס בלבד)

    Returns:
        float | None: המחיר העדכני או None בשגיאה
    """
    try:
        # ייבוא לייט-דינמי של client (למניעת circular import)
        from utils.binance_client import client

        if not client:
            logging.warning("⚠️ Binance client לא מחובר.")
            return None

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




