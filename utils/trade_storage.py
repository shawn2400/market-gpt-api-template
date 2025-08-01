from utils.binance_client import client
import logging

def get_precision_info(symbol: str) -> dict:
    """
    שולף מה-Binance את ה-precision המתאים לסימול:
    - pricePrecision: מספר המקומות אחרי הנקודה למחיר
    - quantityPrecision: מספר המקומות אחרי הנקודה לכמות
    """
    try:
        info = client.get_symbol_info(symbol)
        # Binance may use 'pricePrecision' or 'quotePrecision'
        price_prec = info.get('pricePrecision') if info.get('pricePrecision') is not None else info.get('quotePrecision')
        qty_prec = info.get('baseAssetPrecision')
        return {
            'pricePrecision': int(price_prec),
            'quantityPrecision': int(qty_prec)
        }
    except Exception as e:
        logging.error(f"❌ שגיאה בשליפת precision ל־{symbol}: {e}")
        # ברירת מחדל לערכים סבירים
        return {
            'pricePrecision': 8,
            'quantityPrecision': 8
        }

def round_to_precision(value: float, precision: int) -> float:
    """
    עיגול ערך ל־precision נתון (מספר ספרות אחרי הנקודה).
    """
    factor = 10 ** precision
    # שימוש בעיגול רגיל (חצי למעלה)
    return float(round(value * factor) / factor)















