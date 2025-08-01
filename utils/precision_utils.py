# utils/precision_utils.py

from utils.binance_client import client
import logging

def get_precision_info(symbol: str) -> dict:
    """
    שולף מה-Binance את הפריסיז'ן המתאים לסימול:
    - pricePrecision: מספר המקומות אחרי הנקודה למחיר
    - quantityPrecision: מספר המקומות אחרי הנקודה לכמות
    """
    try:
        info = client.get_symbol_info(symbol)
        # Binance v1: info['quotePrecision'], v2: info['pricePrecision']
        price_prec = info.get('pricePrecision') or info.get('quotePrecision')
        qty_prec = info.get('baseAssetPrecision')
        return {
            'pricePrecision': int(price_prec),
            'quantityPrecision': int(qty_prec)
        }
    except Exception as e:
        logging.error(f"❌ שגיאה בשליפת precision ל־{symbol}: {e}")
        # נחזיר ברירת מחדל
        return {
            'pricePrecision': 8,
            'quantityPrecision': 8
        }

def round_to_precision(value: float, precision: int) -> float:
    """
    עיגול ערך ל־precision נתון (מספר ספרות אחרי הנקודה).
    """
    factor = 10 ** precision
    return float(int(value * factor + 0.5 if value >= 0 else value * factor - 0.5) / factor)








