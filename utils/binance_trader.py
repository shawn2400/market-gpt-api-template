# utils/binance_trade.py
# -*- coding: utf-8 -*-
"""
מעטפת מינימלית לביצוע פקודות FUTURES בבינאנס.
נבנה כ"שימ" כדי לאפשר ל-routes.executor לייבא ולהשתמש בפונקציות סטנדרטיות.
תלויות: python-binance (מותקן אצלך בתדפיסים).
"""

from __future__ import annotations
import os
from typing import Any, Dict, Optional

from binance.client import Client
from binance.enums import (
    SIDE_BUY, SIDE_SELL,
    ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC,
)

# --- יצירת לקוח ---
_API_KEY = os.getenv("BINANCE_API_KEY", "")
_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
_IS_TESTNET = (os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes", "on"))

def _make_client() -> Client:
    if not _API_KEY or not _API_SECRET:
        raise RuntimeError("BINANCE_API_KEY / BINANCE_API_SECRET not set")
    cli = Client(api_key=_API_KEY, api_secret=_API_SECRET, testnet=_IS_TESTNET)
    # שימוש בבסיסים מהסביבה אם סופקו
    f_base = os.getenv("BINANCE_FUTURES_HTTP_BASE")
    if f_base:
        cli.FUTURES_URL = f_base.rstrip("/")
    s_base = os.getenv("BINANCE_SPOT_HTTP_BASE")
    if s_base:
        cli.API_URL = s_base.rstrip("/")
    return cli

# אובייקט לקוח יחיד (לשימוש סינכרוני פשוט)
_client: Optional[Client] = None

def get_client() -> Client:
    global _client
    if _client is None:
        _client = _make_client()
    return _client

# --- עזרי דיוק (אופציונלי – נשתמש אם זמינים) ---
try:
    from utils.precision_utils import apply_price_tick, apply_price_tick_side, apply_qty_step  # type: ignore
except Exception:
    def apply_price_tick(price: float, symbol: str):
        return float(price), str(price)
    def apply_price_tick_side(price: float, symbol: str, side: str):
        return float(price), str(price)
    def apply_qty_step(qty: float, symbol: str):
        return float(qty), str(qty)

# ====================== פעולות מסחר בסיסיות ======================

def ensure_leverage(symbol: str, leverage: int) -> Dict[str, Any]:
    """
    שינוי מינוף לפיוט׳רס.
    """
    cli = get_client()
    leverage = int(max(1, min(int(leverage), 125)))
    res = cli.futures_change_leverage(symbol=symbol.upper(), leverage=leverage)
    return {"ok": True, "result": res}

def ensure_margin_type(symbol: str, margin_type: str = "ISOLATED") -> Dict[str, Any]:
    """
    שינוי מצב מרג׳ין: ISOLATED / CROSSED
    """
    cli = get_client()
    mt = str(margin_type or "ISOLATED").upper()
    if mt not in ("ISOLATED", "CROSSED"):
        mt = "ISOLATED"
    try:
        res = cli.futures_change_margin_type(symbol=symbol.upper(), marginType=mt)
    except Exception as e:
        # אם כבר במצב הרצוי, בינאנס מחזיר שגיאה – נתייחס כ-ok
        msg = str(e)
        if "No need to change margin type" in msg or "code" in msg:
            res = {"note": "already_in_margin_type"}
        else:
            raise
    return {"ok": True, "result": res}

def place_limit_order(
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    time_in_force: str = TIME_IN_FORCE_GTC,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    יצירת פקודת LIMIT בפיוט׳רס. עושה התאמות tick ו-step.
    """
    cli = get_client()
    side_norm = SIDE_BUY if str(side).upper() == "BUY" else SIDE_SELL
    p_adj, p_str = apply_price_tick_side(float(price), symbol, side_norm)
    q_adj, q_str = apply_qty_step(float(quantity), symbol)
    payload = dict(
        symbol=symbol.upper(),
        side=side_norm,
        type=ORDER_TYPE_LIMIT,
        timeInForce=time_in_force,
        quantity=q_str,
        price=p_str,
    )
    payload.update(kwargs or {})
    res = cli.futures_create_order(**payload)
    return {"ok": True, "result": res, "adj": {"qty": q_adj, "qty_str": q_str, "price": p_adj, "price_str": p_str}}

def place_market_order(
    symbol: str,
    side: str,
    quantity: float,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    יצירת פקודת MARKET בפיוט׳רס. עושה התאמות step לכמות.
    """
    cli = get_client()
    side_norm = SIDE_BUY if str(side).upper() == "BUY" else SIDE_SELL
    q_adj, q_str = apply_qty_step(float(quantity), symbol)
    payload = dict(
        symbol=symbol.upper(),
        side=side_norm,
        type=ORDER_TYPE_MARKET,
        quantity=q_str,
    )
    payload.update(kwargs or {})
    res = cli.futures_create_order(**payload)
    return {"ok": True, "result": res, "adj": {"qty": q_adj, "qty_str": q_str}}

def cancel_all(symbol: str) -> Dict[str, Any]:
    """
    ביטול כל הפקודות הפתוחות לסימבול.
    """
    cli = get_client()
    res = cli.futures_cancel_all_open_orders(symbol=symbol.upper())
    return {"ok": True, "result": res}

def cancel_order(symbol: str, order_id: int) -> Dict[str, Any]:
    """
    ביטול פקודה בודדת לפי orderId.
    """
    cli = get_client()
    res = cli.futures_cancel_order(symbol=symbol.upper(), orderId=int(order_id))
    return {"ok": True, "result": res}

def get_position(symbol: str) -> Dict[str, Any]:
    """
    אחזור פוזיציה נוכחית עבור symbol (מידע גולמי מבינאנס).
    """
    cli = get_client()
    arr = cli.futures_position_information(symbol=symbol.upper())
    pos = arr[0] if isinstance(arr, list) and arr else {}
    return {"ok": True, "position": pos}

# עטיפות קצרות לשמות כלליים שה־routes עשוי לייבא
def place_order(symbol: str, side: str, order_type: str, quantity: float, price: Optional[float] = None, **kwargs: Any) -> Dict[str, Any]:
    ot = str(order_type or "").upper()
    if ot == "LIMIT":
        if price is None:
            raise ValueError("price is required for LIMIT")
        return place_limit_order(symbol, side, quantity, price, **kwargs)
    elif ot == "MARKET":
        return place_market_order(symbol, side, quantity, **kwargs)
    else:
        raise ValueError(f"Unsupported order_type: {order_type}")



























