# utils/correlation.py
from typing import List
import numpy as np
import logging

logger = logging.getLogger("algogpt.correlation")

def correlate_to_btc(symbol_data: List[float], btc_data: List[float]) -> float:
    """
    מחשב את מתאם פירסון בין symbol ל-BTC.
    מחזיר ערך בין -1 ל-1.
    """
    if not symbol_data or not btc_data:
        logger.warning("Empty input data for correlation")
        return 0.0
    try:
        return float(np.corrcoef(symbol_data, btc_data)[0, 1])
    except Exception as e:
        logger.error(f"Correlation calculation failed: {e}")
        return 0.0

# Alias לשמירה על תאימות
def compute_correlation(symbol_data: List[float], btc_data: List[float]) -> float:
    return correlate_to_btc(symbol_data, btc_data)




