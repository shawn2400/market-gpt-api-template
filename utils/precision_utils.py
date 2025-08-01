# utils/precision_utils.py

def round_to_precision(value: float, digits: int) -> float:
    """
    Round a numeric value to 'digits' decimal places.
    """
    try:
        return round(value, digits)
    except Exception:
        # במקרה קיצון, החזירו את הערך המקורי
        return value

def get_precision_info(symbol: str) -> dict:
    """
    דוגמה: החזרת פריסיית עיגול לפי סימול.
    במקום הלוגיקה הזו, שלבו את הקריאה ל־Binance או מקור אחר.
    """
    # דיפולט, יש להחליף בלוגיקה אמיתית אם נדרש
    return {
        "pricePrecision": 2,
        "quantityPrecision": 3
    }

















