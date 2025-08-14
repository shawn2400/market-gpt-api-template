# utils/calculate_quantity.py
# שמרתי פונקציות זהות לשמירת תאימות לאזורים ישנים בקוד שמייבאים מכאן.

import logging
from typing import Dict
from utils.quantity_utils import (
    get_precision_info as _get_precision_info_core,
    round_step as _round_step_core,
    round_tick as _round_tick_core,
    calculate_quantity as _calculate_quantity_core,
)

def get_precision_info(symbol: str) -> Dict[str, float]:
    return _get_precision_info_core(symbol)

def round_step(value: float, step: float) -> float:
    return _round_step_core(value, step)

def round_tick(price: float, tick_size: float) -> float:
    return _round_tick_core(price, tick_size)

def calculate_quantity(symbol: str, entry_price: float, leverage: float, budget_usdt: float) -> float:
    try:
        return _calculate_quantity_core(symbol, entry_price, leverage, budget_usdt)
    except Exception as e:
        logging.error(f"[calculate_quantity] ❌ שגיאה בחישוב כמות עבור {symbol}: {e}")
        return 0.0








