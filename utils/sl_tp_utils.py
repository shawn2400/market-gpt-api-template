import numpy as np
import logging
from typing import Tuple
from utils.binance_client import client  # שימוש ב־client שהגדרת

# === חישוב SL/TP בסיסי ===
def calculate_sl_tp(
    entry_price: float,
    direction: str,
    atr: float = None,
    risk_reward: float = 2.0,
    sl_pct: float = 0.7,
    tp_pct: float = 1.4
) -> Tuple[float, float]:
    """
    חישוב SL ו-TP לטרייד, לפי ATR או אחוזים.
    """
    if direction.lower() not in ['long', 'short']:
        raise ValueError("Direction must be 'long' or 'short'")

    try:
        if atr and atr > 0:
            sl_distance = atr * sl_pct
            tp_distance = atr * tp_pct * risk_reward
        else:
            sl_distance = entry_price * 0.0035 * sl_pct
            tp_distance = entry_price * 0.0035 * tp_pct * risk_reward

        if direction.lower() == 'long':
            sl = round(entry_price - sl_distance, 6)
            tp = round(entry_price + tp_distance, 6)
        else:
            sl = round(entry_price + sl_distance, 6)
            tp = round(entry_price - tp_distance, 6)

        return sl, tp
    except Exception as e:
        logging.error(f"[!] שגיאה בחישוב SL/TP: {e}")
        raise

# === חישוב Trailing Stop ===
def trailing_stop(
    entry_price: float,
    direction: str,
    atr: float = None,
    trailing_pct: float = 0.5
) -> float:
    """
    מחשב Trailing Stop לפי ATR או אחוז מהמחיר.
    """
    try:
        if atr and atr > 0:
            trailing_distance = atr * trailing_pct
        else:
            trailing_distance = entry_price * 0.003 * trailing_pct

        if direction.lower() == 'long':
            trailing = round(entry_price - trailing_distance, 6)
        else:
            trailing = round(entry_price + trailing_distance, 6)

        return trailing
    except Exception as e:
        logging.error(f"[!] שגיאה בחישוב Trailing Stop: {e}")
        raise

# === ולידציה ל־SL/TP ===
def validate_sl_tp(
    entry_price: float,
    sl: float,
    tp: float,
    direction: str
) -> bool:
    """
    ולידציה ש-SL/TP נכונים ביחס לכניסה וכיוון.
    """
    if direction.lower() == 'long':
        return sl < entry_price < tp
    else:
        return tp < entry_price < sl

# === שליפת דיוק עבור מטבע (stepSize / tickSize) ===
def get_symbol_precision(symbol: str):
    """
    מחזיר את ה־stepSize (דיוק כמות) ואת ה־tickSize (דיוק מחיר) למטבע מ־Binance Futures.
    """
    try:
        info = client.futures_exchange_info()
        symbol_info = next((s for s in info["symbols"] if s["symbol"] == symbol), None)
        if not symbol_info:
            raise ValueError(f"Symbol {symbol} not found.")

        step_size = None
        tick_size = None

        for f in symbol_info["filters"]:
            if f["filterType"] == "LOT_SIZE":
                step_size = float(f["stepSize"])
            elif f["filterType"] == "PRICE_FILTER":
                tick_size = float(f["tickSize"])

        if step_size is None or tick_size is None:
            raise ValueError(f"Missing step_size or tick_size for {symbol}")

        return {
            "stepSize": step_size,
            "tickSize": tick_size
        }

    except Exception as e:
        logging.error(f"[!] שגיאה בשליפת דיוק עבור {symbol}: {e}")
        return {
            "stepSize": 0.01,
            "tickSize": 0.01
        }






