# utils/precision_utils.py

def round_to_precision(value: float, digits: int) -> float:
    """
    Round a numeric value to 'digits' decimal places.
    """
    try:
        return round(value, digits)
    except Exception:
        # Fallback: return original value on error
        return value

def get_precision_info(symbol: str) -> dict:
    """
    Example stub: return price & quantity precision settings for a given symbol.
    Replace with real Binance‐API call or config lookup as needed.
    """
    # TODO: fetch real info via client.exchange_info or similar
    return {
        "pricePrecision": 2,
        "quantityPrecision": 3,
    }

















