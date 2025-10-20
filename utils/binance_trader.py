# utils/binance_trade.py
# -*- coding: utf-8 -*-
"""
מעטפת מינימלית ומסודרת לביצוע פקודות FUTURES בבינאנס.
מתאימה לשימוש ישיר או ע"י ראוטרים אחרים (executor וכו').
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from binance.client import Client
from binance.enums import (
    SIDE_BUY, SIDE_SELL,
    ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC,
)

# --- קונפיג מהסביבה ---
_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
_API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
_IS_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes", "on")

# אופציונלי: בסיסי URL חלופיים (פרוקסי/מראה)
_FUTURES_HTTP_BASE = (os.getenv("BINANCE_FUTURES_HTTP_BASE") or "").strip().rstrip("/")
_SPOT_HTTP_BASE    = (os.getenv("BINANCE_SPOT_HTTP_BASE") or "").strip().rstrip("/")

_client: Optional[Client] = None


def _make_client() -> Client:
    if not _API_KEY or not _API_SECRET:
        raise RuntimeError("BINANCE_API_KEY / BINANCE_API_SECRET not set")
    cli = Client(api_key=_API_KEY, api_secret=_API_SECRET, testnet=_IS_TESTNET)
    # התאמות בסיס כתובות אם הוגדרו (ספריית python-binance תומכת בשדות אלו)
    if _FUTURES_HTTP_BASE:
        try:
            cli.FUTURES_URL = _FUTURES_HTTP_BASE
        except Exception:
            pass
    if _SPOT_HTTP_BASE:
        try:
            cli.API_URL = _SPOT_HTTP_BASE
        except Exception:
            pass
    return cli


def get_client() -> Client:
    """לקוח סינגלטון עם cache מקומי."""
    global _client
    if _client is None:
        _client = _make_client()
    return _client


# --- דיוק/עיגולים: שימוש במודול חיצוני אם קיים, אחרת נפילה רכה ---
try:
    from utils.precision_utils import (  # type: ignore
        apply_price_tick, apply_price_tick_side, apply_qty_step
    )
except Exception:
    def apply_price_tick(price: float, symbol: str) -> Tuple[float, str]:
        p = float(price)
        return p, f"{p}"

    def apply_price_tick_side(price: float, symbol: str, side: str) -> Tuple[float, str]:
        p = float(price)
        return p, f"{p}"

    def apply_qty_step(qty: float, symbol: str) -> Tuple[float, str]:
        q = float(qty)
        return q, f"{q}"


# --- שירותי עזר אופציונליים ---
def ensure_leverage(symbol: str, leverage: int) -> Dict[str, Any]:
    cli = get_client()
    lev = int(max(1, min(int(leverage), 125)))
    res = cli.futures_change_leverage(symbol=symbol.upper(), leverage=lev)
    return {"ok": True, "result": res, "leverage": lev}


def ensure_margin_type(symbol: str, margin_type: str = "ISOLATED") -> Dict[str, Any]:
    cli = get_client()
    mt = str(margin_type or "ISOLATED").upper()
    if mt not in ("ISOLATED", "CROSSED"):
        mt = "ISOLATED"
    try:
        res = cli.futures_change_margin_type(symbol=symbol.upper(), marginType=mt)
    except Exception as e:
        # אם כבר מוגדר—אין צורך לשנות
        msg = str(e)
        if "No need to change margin type" in msg or "margin type same" in msg.lower():
            res = {"note": "already_in_margin_type"}
        else:
            raise
    return {"ok": True, "result": res, "margin_type": mt}


# --- פעולות הזמנה ---
def place_limit_order(
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    time_in_force: str = TIME_IN_FORCE_GTC,
    **kwargs: Any,
) -> Dict[str, Any]:
    if not symbol or side.upper() not in ("BUY", "SELL") or quantity <= 0 or price <= 0:
        raise ValueError("bad_args: symbol/side/quantity/price")

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
    # תמיכה בשדות binance כגון newClientOrderId, positionSide, reduceOnly וכו'
    payload.update(kwargs or {})

    res = cli.futures_create_order(**payload)
    return {
        "ok": True,
        "result": res,
        "adj": {"qty": q_adj, "qty_str": q_str, "price": p_adj, "price_str": p_str},
        "payload": payload,
    }


def place_market_order(
    symbol: str,
    side: str,
    quantity: float,
    **kwargs: Any,
) -> Dict[str, Any]:
    if not symbol or side.upper() not in ("BUY", "SELL") or quantity <= 0:
        raise ValueError("bad_args: symbol/side/quantity")

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
    return {
        "ok": True,
        "result": res,
        "adj": {"qty": q_adj, "qty_str": q_str},
        "payload": payload,
    }


def place_order(
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    price: Optional[float] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    ot = str(order_type or "").upper()
    if ot == "LIMIT":
        if price is None:
            raise ValueError("price is required for LIMIT")
        return place_limit_order(symbol, side, quantity, price, **kwargs)
    if ot == "MARKET":
        return place_market_order(symbol, side, quantity, **kwargs)
    raise ValueError(f"Unsupported order_type: {order_type}")


# --- ביטולים/שאילתות ---
def cancel_all(symbol: str) -> Dict[str, Any]:
    cli = get_client()
    res = cli.futures_cancel_all_open_orders(symbol=symbol.upper())
    return {"ok": True, "result": res}


def cancel_order(symbol: str, order_id: int) -> Dict[str, Any]:
    cli = get_client()
    res = cli.futures_cancel_order(symbol=symbol.upper(), orderId=int(order_id))
    return {"ok": True, "result": res}


def get_position(symbol: str) -> Dict[str, Any]:
    cli = get_client()
    arr = cli.futures_position_information(symbol=symbol.upper())
    pos = arr[0] if isinstance(arr, list) and arr else {}
    return {"ok": True, "position": pos}





















