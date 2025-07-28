from math import floor
from utils.binance_client import client

def get_step_size(symbol: str) -> float:
    """
    שולף את ה־stepSize (גודל היחידה) ממידע הבורסה של Binance Futures.
    """
    try:
        info = client.futures_exchange_info()
        for s in info.get("symbols", []):
            if s["symbol"] == symbol:
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        return float(f["stepSize"])
    except Exception as e:
        print(f"[!] שגיאה בשליפת stepSize עבור {symbol}: {e}")
    return 0.01  # ברירת מחדל שמרנית

def calculate_quantity(symbol: str, entry_price: float, leverage: float, budget_usdt: float) -> float:
    """
    מחשב כמות נכונה של חוזים למסחר בפיוצ'רס, לפי תקציב, מינוף ומחיר כניסה.
    תוצאה מעוגלת לפי stepSize של Binance.
    """
    try:
        if entry_price <= 0:
            raise ValueError("Entry price must be positive")

        step_size = get_step_size(symbol)
        raw_qty = (budget_usdt * leverage) / entry_price
        qty = floor(raw_qty / step_size) * step_size

        if qty <= 0:
            raise ValueError(f"כמות לא חוקית – אולי התקציב קטן מדי או leverage נמוך מדי (חושב: {raw_qty})")

        return round(qty, 6)
    except Exception as e:
        print(f"[!] שגיאה בחישוב כמות עבור {symbol}: {e}")
        return 0.0


