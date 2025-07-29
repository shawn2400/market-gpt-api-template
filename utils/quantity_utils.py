# utils/quantity_utils.py

import math
from utils.binance_client import client
import logging

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

def round_step(quantity, step_size: float) -> float:
    """
    עיגול כמות לפי stepSize
    """
    try:
        return math.floor(quantity / step_size) * step_size
    except Exception as e:
        logging.error(f"[!] שגיאה בעיגול כמות לפי stepSize: {e}")
        return 0.0

def get_symbol_precision(symbol: str) -> dict:
    """
    מחזיר את הגדרות stepSize ו־minQty לסימבול מסוים
    """
    try:
        exchange_info = client.futures_exchange_info()
        symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)
        if not symbol_info:
            raise ValueError(f"Symbol {symbol} not found in exchange info")

        lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), {})
        return {
            "stepSize": float(lot_size_filter.get("stepSize", 0.01)),
            "minQty": float(lot_size_filter.get("minQty", 0.0))
        }
    except Exception as e:
        logging.error(f"[!] שגיאה בשליפת precision עבור {symbol}: {e}")
        return {"stepSize": 0.01, "minQty": 0.0}

def calculate_quantity(budget_usd, entry_price, leverage, symbol=None) -> float:
    """
    מחשב כמות (quantity) בהתחשב בתקציב, מינוף, מחיר, stepSize של Binance
    """
    try:
        step_size = 0.01
        if symbol:
            precision = get_symbol_precision(symbol)
            step_size = precision["stepSize"]

        raw_qty = (budget_usd * leverage) / entry_price
        qty = round_step(raw_qty, step_size)
        return round(qty, 6)
    except Exception as e:
        logging.error(f"[!] שגיאה בחישוב כמות: {e}")
        return 0.0

def auto_risk_allocation(entry_price, stop_price, total_budget, risk_percent=2, leverage=1, symbol=None) -> dict:
    """
    מחשב כמות לפי סיכון אחוזי מהתקציב, תוך שימוש ב־stepSize
    """
    try:
        risk_per_trade = total_budget * (risk_percent / 100)
        risk_per_unit = abs(entry_price - stop_price)
        if risk_per_unit == 0:
            raise ValueError("Stop price and entry price זהים – אי אפשר לחשב סיכון")

        raw_qty = risk_per_trade / risk_per_unit
        capital_required = raw_qty * entry_price

        if symbol:
            step_size = get_symbol_precision(symbol)["stepSize"]
            qty = round_step(raw_qty, step_size)
        else:
            qty = round(raw_qty, 6)

        return {
            "capital_required": min(capital_required, total_budget),
            "quantity": qty
        }

    except Exception as e:
        logging.error(f"[!] שגיאה בחישוב חלוקת סיכון: {e}")
        return {
            "capital_required": total_budget,
            "quantity": 0
        }



