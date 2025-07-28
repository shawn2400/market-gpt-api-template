# utils/calculate_quantity.py

def calculate_quantity(budget_usdt, entry_price, leverage=10, precision=3):
    """
    מחשב את כמות המטבעות לפי תקציב, מחיר כניסה ומינוף.
    :param budget_usdt: תקציב ב-USDT (למשל: 100)
    :param entry_price: מחיר כניסה של המטבע (float)
    :param leverage: מינוף נבחר (int)
    :param precision: מספר ספרות עשרוניות לעיגול הכמות
    :return: כמות float
    """
    try:
        if entry_price <= 0:
            raise ValueError("מחיר כניסה לא חוקי")
        if leverage <= 0:
            leverage = 1

        # תקציב אפקטיבי כולל מינוף
        effective_usdt = budget_usdt * leverage

        qty = effective_usdt / entry_price
        return round(qty, precision)

    except Exception as e:
        print(f"[!] שגיאה בחישוב כמות: {e}")
        return 0
