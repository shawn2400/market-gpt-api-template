# utils/precision_utils.py

from decimal import Decimal
from typing import Dict

from utils.binance_client import client


def get_precision_info(symbol: str) -> Dict[str, int]:
    """
    מחזיר dict עם שני ערכים:
      - 'quantity_precision': מספר הספרות אחרי הנקודה לכמות
      - 'price_precision': מספר הספרות אחרי הנקודה למחיר
    """
    info = client.get_symbol_info(symbol)
    if not info:
        raise ValueError(f"Could not fetch symbol info for {symbol}")

    # חפש את הפילטרים המתאימים
    lot = next(f for f in info['filters'] if f['filterType'] == 'LOT_SIZE')
    price = next(f for f in info['filters'] if f['filterType'] == 'PRICE_FILTER')

    step_size = lot['stepSize']
    tick_size = price['tickSize']

    def _count_decimals(val: str) -> int:
        d = Decimal(val)
        return abs(d.as_tuple().exponent)

    return {
        'quantity_precision': _count_decimals(step_size),
        'price_precision': _count_decimals(tick_size),
    }
