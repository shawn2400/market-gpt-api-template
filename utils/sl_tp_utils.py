# utils/sltp.py
from __future__ import annotations
from typing import Optional, Tuple


def calc_sl_tp(
    entry: float,
    side: str,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    atr: Optional[float] = None,
    atr_mult: float = 1.5,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Calculate Stop Loss (SL) and Take Profit (TP).

    Args:
        entry (float): entry price
        side (str): "LONG" or "SHORT"
        sl (Optional[float]): stop loss level (absolute or relative %)
        tp (Optional[float]): take profit level (absolute or relative %)
        atr (Optional[float]): ATR (Average True Range) for volatility-based calc
        atr_mult (float): ATR multiplier (default 1.5)

    Returns:
        Tuple (sl_price, tp_price)
    """
    side = side.upper()
    sl_price, tp_price = None, None

    # --- ATR based fallback ---
    if atr and (sl is None and tp is None):
        if side == "LONG":
            sl_price = entry - atr_mult * atr
            tp_price = entry + atr_mult * atr
        else:  # SHORT
            sl_price = entry + atr_mult * atr
            tp_price = entry - atr_mult * atr
        return sl_price, tp_price

    # --- Stop Loss ---
    if sl is not None:
        if sl < 1:  # interpret as %
            if side == "LONG":
                sl_price = entry * (1 - sl)
            else:  # SHORT
                sl_price = entry * (1 + sl)
        else:  # absolute price
            sl_price = sl

    # --- Take Profit ---
    if tp is not None:
        if tp < 1:  # interpret as %
            if side == "LONG":
                tp_price = entry * (1 + tp)
            else:  # SHORT
                tp_price = entry * (1 - tp)
        else:  # absolute price
            tp_price = tp

    return sl_price, tp_price








       






