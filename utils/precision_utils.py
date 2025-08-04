# utils/precision_utils.py
def round_to_precision(value: float, digits: int) -> float:
    try:
        return round(value, digits)
    except Exception:
        return value

def get_precision_info(symbol: str) -> dict:
    # Stub – החלף בשאיבה אמיתית מ־Binance אם צריך.
    return {"pricePrecision": 2, "quantityPrecision": 3}




















