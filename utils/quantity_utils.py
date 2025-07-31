# utils/quantity_utils.py

from utils.precision_utils import get_precision_info

def calculate_quantity(symbol: str, price: float, leverage: float, budget: float) -> float:
    """
    מחשב את כמות המטבעות לפי תקציב, מחיר, ומינוף.
    כולל עיגול לפי precision.
    """
    notional = budget * leverage
    raw_qty = notional / price

    precision_info = get_precision_info(symbol)
    step_size = precision_info.get("stepSize", 0.01)

    # עיגול מטה לפי step size
    precision = abs(int(round(-1 * (step_size).as_integer_ratio()[1]).bit_length() - 1))
    quantity = round(raw_qty - (raw_qty % step_size), precision)

    return quantity





