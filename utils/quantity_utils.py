# utils/quantity_utils.py
def calculate_quantity(budget_usdt, entry_price, leverage, precision=3):
    """
    חישוב כמות לפי תקציב ב-USDT, מחיר כניסה ומינוף
    """
    if entry_price <= 0 or leverage <= 0:
        return 0
    raw_qty = (budget_usdt * leverage) / entry_price
    return round(raw_qty, precision)

