# utils/quantity_utils.py

import math
from typing import Any, Optional
from utils.precision_utils import get_precision_info
from utils.binance_client import client
import logging

def get_price(symbol: str) -> Optional[float]:
    """
    מחזיר את מחיר הסימבול הנוכחי מה־client.
    מחזיר None במקרה של שגיאה.
    """
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker['price'])
    except Exception as e:
        logging.warning(f"[quantity_utils] שגיאה בשליפת מחיר עבור {symbol}: {e}")
        return None

def calculate_quantity_usdt(symbol: str, usdt_amount: float) -> float:
    """
    מחשב כמות מטבע לפי סכום ב־USDT.
    """
    price = get_price(symbol)
    if not price or price <= 0 or usdt_amount <= 0:
        return 0.0

    raw_qty = usdt_amount / price
    precision = get_precision_info(symbol).get('quantityPrecision', 4)
    return round(raw_qty, precision)

def auto_risk_allocation(symbol: str, risk_usd: float) -> float:
    """
    מחשב כמות שמייצגת סיכון מקסימלי בדולרים.
    לדוגמה: אם SL רחוק 2% ויש תקציב סיכון $10, אז מחשב כמות כך שהפסד לא יעבור 10$.
    (נדרשת הרחבה בהמשך עם SL).
    """
    price = get_price(symbol)
    if not price or risk_usd <= 0:
        return 0.0

    raw_qty = risk_usd / price
    precision = get_precision_info(symbol).get('quantityPrecision', 4)
    return round(raw_qty, precision)

def calculate_quantity(symbol: str, price: float, leverage: float, budget: float) -> float:
    """
    מחשב כמות לפי תקציב, מחיר ומינוף.
    כולל עיגול לפי שלב מינימלי (step size).
    """
    if price <= 0 or leverage <= 0 or budget <= 0:
        return 0.0

    notional = budget * leverage
    raw_qty = notional / price

    precision_info: Any = get_precision_info(symbol)
    step_size = float(precision_info.get('stepSize', 1 / (10 ** precision_info.get('quantityPrecision', 4))))
    quantity_precision = int(round(-math.log10(step_size))) if step_size < 1 else 0

    quantity = math.floor(raw_qty / step_size) * step_size

    return round(quantity, quantity_precision)







