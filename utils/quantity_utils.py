from utils.precision_utils import get_precision_info
import math

def calculate_quantity(symbol: str, price: float, leverage: float, budget: float) -> float:
    """# utils/quantity_utils.py

from typing import Tuple
from utils.precision_utils import get_precision_info
from utils.binance_client import client

def calculate_quantity(symbol: str, usdt_amount: float) -> float:
    """
    מחשב כמות של Symbol לפי סכום USDT נתון.
    """
    ticker = client.get_symbol_ticker(symbol=symbol)
    price = float(ticker['price'])
    raw_qty = usdt_amount / price

    precision = get_precision_info(symbol)['quantity_precision']
    return round(raw_qty, precision)

def auto_risk_allocation(symbol: str, risk_usd: float) -> float:
    """
    מחשב כמות עיסקה כך שהסיכון (ב־USD) לא יעלה על risk_usd.
    הנחה: הסיכון = סכום ההשקעה (ללא stop-loss), כלומר כמות * price = risk_usd.
    """
    # קבל מחיר נוכחי
    ticker = client.get_symbol_ticker(symbol=symbol)
    price = float(ticker['price'])

    # חשב כמות “גסה”
    raw_qty = risk_usd / price

    # סגור לפי הדיוק של הבורסה
    precision = get_precision_info(symbol)['quantity_precision']
    return round(raw_qty, precision)

    מחשב את כמות המטבעות לפי תקציב, מחיר, ומינוף.
    כולל עיגול לפי stepSize מתוך Binance.
    """
    if price <= 0 or leverage <= 0 or budget <= 0:
        return 0.0

    notional = budget * leverage
    raw_qty = notional / price

    precision_info = get_precision_info(symbol)
    step_size = float(precision_info.get("stepSize", 0.01))

    # עיגול לפי step size
    precision = int(round(-math.log10(step_size))) if step_size < 1 else 0
    quantity = math.floor(raw_qty / step_size) * step_size

    return round(quantity, precision)





