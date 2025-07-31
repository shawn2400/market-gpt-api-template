from utils.precision_utils import get_precision_info
import math

def calculate_quantity(symbol: str, price: float, leverage: float, budget: float) -> float:
    """
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





