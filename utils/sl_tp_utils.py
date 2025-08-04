# utils/sl_tp_utils.py

import logging
from typing import Tuple
from utils.binance_client import client

def calculate_sl_tp(
    entry_price: float,
    direction: str,
    atr: float = None,
    risk_reward: float = 2.0,
    sl_pct: float = 0.7,
    tp_pct: float = 1.4
) -> Tuple[float, float]:
    direction = direction.lower()
    if direction not in ['long', 'short']:
        raise ValueError("Direction must be 'long' or 'short'")
    try:
        if atr and atr > 0:
            sl_distance = atr * sl_pct
            tp_distance = atr * tp_pct * risk_reward
        else:
            sl_distance = entry_price * 0.0035 * sl_pct
            tp_distance = entry_price * 0.0035 * tp_pct * risk_reward

        if direction == 'long':
            sl = round(entry_price - sl_distance, 6)
            tp = round(entry_price + tp_distance, 6)
            if not (sl < entry_price < tp):
                sl, tp = entry_price * 0.985, entry_price * 1.025
        else:
            sl = round(entry_price + sl_distance, 6)
            tp = round(entry_price - tp_distance, 6)
            if not (tp < entry_price < sl):
                sl, tp = entry_price * 1.015, entry_price * 0.975
        return sl, tp
    except Exception as e:
        logging.error(f"[!] שגיאה בחישוב SL/TP: {e}")
        if direction == "long":
            return round(entry_price * 0.99, 6), round(entry_price * 1.02, 6)
        else:
            return round(entry_price * 1.01, 6), round(entry_price * 0.98, 6)


       






