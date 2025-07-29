# utils/get_live_price.py

import logging

def get_live_price(symbol: str, is_futures: bool = True, source: str = "last") -> float | None:
    """
    מחזיר מחיר עדכני מממשק Binance (Futures/Spot).
    
    Args:
        symbol (str): לדוג' 'BTCUSDT'
        is_futures (bool): True – פיוצ'רס, False – ספוט
        source (str): 'last' (ברירת מחדל), 'mark', 'index' – רק עבור פיוצ'רס

    Returns:
        float | None: מחיר עדכני או None במקרה של שגיאה
    """
    try:
        # ייבוא דינמי כדי למנוע circular import
        from utils.binance_client import client

        symbol = symbol.upper().strip()
        if not client:
            logging.warning("⚠️ Binance client לא מחובר.")
            return None

        if is_futures:
            if source == "mark":
                data = client.futures_mark_price(symbol=symbol)
                return float(data.get("markPrice", 0))
            elif source == "index":
                data = client.futures_index_price(symbol=symbol)
                return float(data.get("indexPrice", 0))
            else:  # 'last' (ברירת מחדל)
                data = client.futures_symbol_ticker(symbol=symbol)
                return float(data.get("price", 0))
        else:
            data = client.get_symbol_ticker(symbol=symbol)
            return float(data.get("price", 0))

    except Exception as e:
        logging.error(f"[get_live_price] שגיאה בשליפת מחיר עבור {symbol} ({source}): {e}")
        return None

# דוגמת בדיקה עצמאית – להריץ מהטרמינל:
if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    price = get_live_price(symbol, is_futures=True, source="last")
    print(f"מחיר {symbol}: {price if price else 'שגיאה'}")





