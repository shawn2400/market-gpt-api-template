# utils/get_live_price.py

import logging
from typing import Optional

def get_live_price(symbol: str, is_futures: bool = True, source: str = "last") -> Optional[float]:
    """
    מחזיר מחיר עדכני מ־Binance (Spot או Futures)
    
    Args:
        symbol (str): לדוגמה: "BTCUSDT"
        is_futures (bool): האם לשלוף מ־Futures (True) או Spot (False)
        source (str): מקור המחיר: 'last', 'mark', 'index' (רק עבור Futures)
    
    Returns:
        float | None: מחיר עדכני או None במקרה של שגיאה
    """
    try:
        from utils.binance_client import client

        symbol = symbol.upper().strip()
        if not client:
            logging.warning("⚠️ Binance client לא מאותחל.")
            return None

        if is_futures:
            if source == "mark":
                data = client.futures_mark_price(symbol=symbol)
                return float(data.get("markPrice"))
            elif source == "index":
                data = client.futures_index_price(symbol=symbol)
                return float(data.get("indexPrice"))
            else:
                data = client.futures_symbol_ticker(symbol=symbol)
                return float(data.get("price"))
        else:
            data = client.get_symbol_ticker(symbol=symbol)
            return float(data.get("price"))

    except Exception as e:
        logging.error(f"[get_live_price] שגיאה בשליפת מחיר עבור {symbol} (source={source}): {e}")
        return None

# בדיקה עצמית (run standalone)
if __name__ == "__main__":
    symbol = "BTCUSDT"
    price = get_live_price(symbol)
    print(f"🔹 מחיר {symbol}: {price if price else 'שגיאה'}")






