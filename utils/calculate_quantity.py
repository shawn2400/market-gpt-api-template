import logging
from math import floor
from utils.binance_client import client

def get_precision_info(symbol: str) -> dict:
    """
    שולף stepSize ו-minQty (וגם tickSize) ל־symbol מ־Binance Futures.
    תמיד מחזיר dict מלא!
    """
    try:
        info = client.futures_exchange_info()
        for s in info.get("symbols", []):
            if s["symbol"] == symbol:
                data = {}
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        data["stepSize"] = float(f["stepSize"])
                        data["minQty"] = float(f["minQty"])
                    if f["filterType"] == "PRICE_FILTER":
                        data["tickSize"] = float(f["tickSize"])
                # ערכי ברירת מחדל אם חסרים
                return {
                    "stepSize": data.get("stepSize", 0.01),
                    "minQty": data.get("minQty", 0.0),
                    "tickSize": data.get("tickSize", 0.01)
                }
    except Exception as e:
        logging.error(f"[!] שגיאה ב־get_precision_info עבור {symbol}: {e}")
    return {"stepSize": 0.01, "minQty": 0.0, "tickSize": 0.01}

def calculate_quantity(symbol: str, entry_price: float, leverage: float, budget_usdt: float) -> float:
    """
    מחשב כמות חוזים לפי תקציב, מחיר ומינוף – כולל minQty/stepSize.
    """
    try:
        if entry_price <= 0:
            raise ValueError("Entry price must be positive")

        precision = get_precision_info(symbol)
        step_size = precision.get("stepSize", 0.01)
        min_qty = precision.get("minQty", 0.0)

        raw_qty = (budget_usdt * leverage) / entry_price
        qty = floor(raw_qty / step_size) * step_size

        if qty < min_qty:
            logging.warning(f"[!] כמות נמוכה מהמינימום: {qty} < {min_qty} (symbol={symbol})")
            return 0.0

        return round(qty, 6)
    except Exception as e:
        logging.error(f"[!] שגיאה בחישוב כמות עבור {symbol}: {e}")
        return 0.0





