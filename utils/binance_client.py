# utils/binance_client.py
from __future__ import annotations
import os
import logging
from typing import Any, Dict, List, Optional, Iterable
from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger("algogpt.binance")

# === Load API Keys ===
API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
if not API_KEY or not API_SECRET:
    logger.error("[binance_client] Missing API keys")
    raise RuntimeError("Missing Binance API keys")

# === Init client (Futures only) ===
client = Client(API_KEY, API_SECRET)
client.API_URL = "https://fapi.binance.com/fapi"

# === ENV behavior ===
WORKING_TYPE = os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE").upper()  # MARK_PRICE / CONTRACT_PRICE
RECV_WINDOW = int(os.getenv("BINANCE_RECV_WINDOW", "45000"))

# === Defaults for precision fallbacks ===
DEFAULT_QTY_STEP_STR = "0.001"
DEFAULT_PRICE_TICK_STR = "0.01"
DEFAULT_MIN_NOTIONAL = 5.0

# ==================== Core Safe Calls ====================
def fapi_ping() -> bool:
    try:
        client.futures_ping()
        return True
    except Exception as e:
        logger.warning("Futures ping failed: %s", e)
        return False

def futures_exchange_info_safe() -> Optional[Dict[str, Any]]:
    try:
        return client.futures_exchange_info()
    except Exception as e:
        logger.error("Failed to fetch futures_exchange_info: %s", e)
        return None

def futures_balance() -> List[Dict[str, Any]]:
    try:
        return client.futures_account_balance() or []
    except Exception as e:
        logger.error("Failed to fetch futures_balance: %s", e)
        return []

def futures_mark_price(symbol: str) -> Optional[float]:
    try:
        data = client.futures_mark_price(symbol=symbol)
        return float(data["markPrice"])
    except Exception as e:
        logger.error("Failed to fetch mark price for %s: %s", symbol, e)
        return None

# === compat: get_price → משתמש ב-mark price ===
def get_price(symbol: str) -> Optional[float]:
    return futures_mark_price(symbol)

def get_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        info = futures_exchange_info_safe()
        if not info:
            return None
        for s in info.get("symbols", []):
            if (s.get("symbol") or "").upper() == symbol.upper():
                return s
    except Exception as e:
        logger.error("Failed get_symbol_info: %s", e)
    return None

def get_symbol_filters(symbol: str) -> Optional[Dict[str, Any]]:
    """
    מחלץ פילטרים (minQty, stepSize, tickSize, minNotional) עבור סימבול נתון.
    """
    try:
        info = get_symbol_info(symbol)
        if not info:
            return None
        filters = {}
        for f in info.get("filters", []):
            ftype = f.get("filterType")
            if ftype == "LOT_SIZE":
                filters["minQty"] = f.get("minQty")
                filters["stepSize"] = f.get("stepSize")
            elif ftype == "PRICE_FILTER":
                filters["tickSize"] = f.get("tickSize")
            elif ftype == "MIN_NOTIONAL":
                filters["minNotional"] = f.get("notional") or f.get("minNotional")
        return filters
    except Exception as e:
        logger.error("Failed get_symbol_filters: %s", e)
        return None

# ==================== Helpers: precision & side ====================
def _decimals_from_tick(tick_str: str) -> int:
    if "." not in tick_str:
        return 0
    frac = tick_str.split(".")[1]
    # strip trailing zeros
    while frac and frac.endswith("0"):
        frac = frac[:-1]
    return len(frac)

def _quantize_price(symbol: str, price: float) -> str:
    filters = get_symbol_filters(symbol) or {}
    tick = float(filters.get("tickSize") or DEFAULT_PRICE_TICK_STR)
    if tick <= 0:
        tick = float(DEFAULT_PRICE_TICK_STR)
    steps = round(price / tick)
    adj = steps * tick
    decs = _decimals_from_tick(str(filters.get("tickSize") or DEFAULT_PRICE_TICK_STR))
    return f"{adj:.{decs}f}"

def _position_side_from_amt(amt: float) -> str:
    return "LONG" if amt > 0 else "SHORT"

def _order_side_for_close(pos_side: str) -> str:
    pos_side = (pos_side or "").upper()
    if pos_side == "LONG":
        return "SELL"
    if pos_side == "SHORT":
        return "BUY"
    # default: assume LONG
    return "SELL"

# ==================== Positions ====================
def get_open_positions(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    מחזיר רשימת פוזיציות פתוחות בחשבון Futures.
    אם מועבר symbol → מסנן לפי סימבול.
    """
    try:
        acc_info = client.futures_account()
        positions = acc_info.get("positions", [])
        out = []
        for pos in positions:
            amt = float(pos.get("positionAmt", "0"))
            if abs(amt) > 1e-12:
                if symbol is None or (pos.get("symbol") or "").upper() == symbol.upper():
                    out.append(pos)
        return out
    except Exception as e:
        logger.error("Failed to get open positions: %s", e)
        return []

# === compat: alias לרואטר ישן ===
def futures_open_positions_safe(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    return get_open_positions(symbol)

def get_single_position(symbol: str) -> Optional[Dict[str, Any]]:
    for p in get_open_positions(symbol):
        return p
    return None

# ==================== Orders ====================
def futures_create_order(**kwargs) -> Dict[str, Any]:
    """
    יוצר פקודת Futures (Limit / Market / Stop).
    עטיפה בטוחה עם טיפול בשגיאות.
    """
    try:
        return client.futures_create_order(**kwargs)
    except BinanceAPIException as e:
        logger.error("BinanceAPIException: %s", e)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("Failed to create futures order: %s", e)
        return {"ok": False, "error": str(e)}

def futures_cancel_all_orders(symbol: str) -> Dict[str, Any]:
    """
    מבטל את כל ההוראות הפתוחות לסימבול מסוים.
    """
    try:
        return client.futures_cancel_all_open_orders(symbol=symbol)
    except Exception as e:
        logger.error("Failed to cancel orders for %s: %s", symbol, e)
        return {"ok": False, "error": str(e)}

def futures_cancel_order(symbol: str, orderId: int | str) -> Dict[str, Any]:
    try:
        return client.futures_cancel_order(symbol=symbol.upper(), orderId=orderId)
    except Exception as e:
        logger.error("Failed to cancel order %s/%s: %s", symbol, orderId, e)
        return {"ok": False, "error": str(e)}

def get_open_orders(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        if symbol:
            return client.futures_get_open_orders(symbol=symbol.upper()) or []
        return client.futures_get_open_orders() or []
    except Exception as e:
        logger.error("Failed to get open orders: %s", e)
        return []

# ==================== Leverage ====================
def set_leverage(symbol: str, leverage: int) -> Dict[str, Any]:
    """
    קובע מינוף חדש לסימבול נתון.
    """
    try:
        return client.futures_change_leverage(symbol=symbol.upper(), leverage=int(leverage))
    except Exception as e:
        logger.error("Failed to set leverage %s for %s: %s", leverage, symbol, e)
        return {"ok": False, "error": str(e)}

# ==================== Cancel+Recreate (Fallback) ====================
def _cancel_closing_orders(symbol: str, types: Iterable[str]) -> int:
    """
    מבטל רק הוראות סגירה (STOP/TAKE_PROFIT) לסימבול.
    מחזיר כמה הוראות בוטלו.
    """
    open_orders = get_open_orders(symbol)
    count = 0
    types = set(t.upper() for t in types)
    for o in open_orders:
        o_type = (o.get("type") or o.get("origType") or "").upper()
        reduce_only = bool(o.get("reduceOnly")) if "reduceOnly" in o else False
        close_pos = bool(o.get("closePosition")) if "closePosition" in o else False
        if o_type in types and (reduce_only or close_pos or True):
            # שים לב: חלק מה־SDK לא מחזיר reduceOnly — לכן נבטל לפי type בלבד.
            oid = o.get("orderId")
            if oid is not None:
                try:
                    client.futures_cancel_order(symbol=symbol.upper(), orderId=oid)
                    count += 1
                except Exception as e:
                    logger.warning("Cancel order failed %s/%s: %s", symbol, oid, e)
    return count

def modify_stop_loss(symbol: str, new_sl_price: float, position_side: Optional[str] = None) -> Dict[str, Any]:
    """
    Fallback: מבטל STOP/STOP_MARKET קיימים ומקים חדש כ-closePosition=True.
    """
    try:
        pos = get_single_position(symbol)
        if not pos:
            return {"ok": False, "error": f"No open position for {symbol}"}

        amt = float(pos.get("positionAmt", "0"))
        if abs(amt) < 1e-12:
            return {"ok": False, "error": f"No non-zero position for {symbol}"}

        pos_side = position_side or _position_side_from_amt(amt)
        side = _order_side_for_close(pos_side)
        qprice = _quantize_price(symbol, float(new_sl_price))

        canceled = _cancel_closing_orders(symbol, types=("STOP", "STOP_MARKET"))

        order = client.futures_create_order(
            symbol=symbol.upper(),
            side=side,                      # SELL to close LONG, BUY to close SHORT
            type="STOP_MARKET",
            stopPrice=qprice,
            reduceOnly=True,
            closePosition=True,            # כל הכמות
            workingType=WORKING_TYPE,      # MARK_PRICE/CONTRACT_PRICE
            recvWindow=RECV_WINDOW,
        )
        return {"ok": True, "canceled": canceled, "order": order, "stopPrice": qprice}
    except BinanceAPIException as e:
        logger.error("modify_stop_loss failed: %s", e)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("modify_stop_loss failed: %s", e)
        return {"ok": False, "error": str(e)}

def modify_take_profit(symbol: str, new_tp_price: float, position_side: Optional[str] = None) -> Dict[str, Any]:
    """
    Fallback: מבטל TAKE_PROFIT/TAKE_PROFIT_MARKET קיימים ומקים חדש כ-closePosition=True.
    """
    try:
        pos = get_single_position(symbol)
        if not pos:
            return {"ok": False, "error": f"No open position for {symbol}"}

        amt = float(pos.get("positionAmt", "0"))
        if abs(amt) < 1e-12:
            return {"ok": False, "error": f"No non-zero position for {symbol}"}

        pos_side = position_side or _position_side_from_amt(amt)
        side = _order_side_for_close(pos_side)
        qprice = _quantize_price(symbol, float(new_tp_price))

        canceled = _cancel_closing_orders(symbol, types=("TAKE_PROFIT", "TAKE_PROFIT_MARKET"))

        order = client.futures_create_order(
            symbol=symbol.upper(),
            side=side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=qprice,
            reduceOnly=True,
            closePosition=True,
            workingType=WORKING_TYPE,
            recvWindow=RECV_WINDOW,
        )
        return {"ok": True, "canceled": canceled, "order": order, "stopPrice": qprice}
    except BinanceAPIException as e:
        logger.error("modify_take_profit failed: %s", e)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("modify_take_profit failed: %s", e)
        return {"ok": False, "error": str(e)}

# ==================== Convenience: Breakeven ====================
def set_breakeven_stop(symbol: str, offset_bps: float = 0.0) -> Dict[str, Any]:
    """
    שם SL על מחיר כניסה (entryPrice) +/− offset בבסיס נקודות (bps).
    offset_bps>0: LONG → SL גבוה מהכניסה; SHORT → SL נמוך מהכניסה (במרחק bps).
    """
    pos = get_single_position(symbol)
    if not pos:
        return {"ok": False, "error": f"No open position for {symbol}"}

    entry = float(pos.get("entryPrice") or 0.0)
    if entry <= 0:
        return {"ok": False, "error": f"Invalid entryPrice for {symbol}"}

    amt = float(pos.get("positionAmt", "0"))
    pos_side = _position_side_from_amt(amt)

    # חשב מחיר SL סביב הכניסה
    if pos_side == "LONG":
        sl = entry * (1.0 + (offset_bps / 10000.0))
    else:  # SHORT
        sl = entry * (1.0 - (offset_bps / 10000.0))

    return modify_stop_loss(symbol, sl, position_side=pos_side)

# ==================== Exports ====================
__all__ = [
    "client",
    "fapi_ping",
    "futures_exchange_info_safe",
    "futures_balance",
    "futures_mark_price",
    "get_price",
    "get_symbol_info",
    "get_symbol_filters",
    "get_open_positions",
    "futures_open_positions_safe",
    "get_single_position",
    "futures_create_order",
    "futures_cancel_all_orders",
    "futures_cancel_order",
    "get_open_orders",
    "set_leverage",
    "modify_stop_loss",
    "modify_take_profit",
    "set_breakeven_stop",
    "DEFAULT_QTY_STEP_STR",
    "DEFAULT_PRICE_TICK_STR",
    "DEFAULT_MIN_NOTIONAL",
]




















































































































































































