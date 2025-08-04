# utils/precision_utils.py

def round_to_precision(value: float, digits: int) -> float:
    """Round a numeric value to 'digits' decimal places."""
    try:
        return round(value, digits)
    except Exception:
        return value

def get_precision_info(symbol: str) -> dict:
    """
    הפונקציה הזו דורשת החלפה בגרסה חיה שמביאה פרמטרים מהבורסה בפועל!
    **הגרסה כאן היא placeholder** – בקוד רץ יש לשאוב מ־binance_client/get_exchange_info().
    """
    return {
        "pricePrecision": 2,
        "quantityPrecision": 3,
    }





















