# -*- coding: utf-8 -*-
"""
Safe Order Parameters Builder
Prevents APIError -4061 (position side mismatch) and -1106 (reduceOnly errors)
"""
from __future__ import annotations
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)

# Import position_mode safely
try:
    from utils.position_mode import get_dual_position_mode
except ImportError:
    def get_dual_position_mode() -> bool:
        return False

TICK_FALLBACK = Decimal("0.0001")


def quantize_price(price: float, tick_size: Optional[str]) -> str:
    """
    Quantize price to tick size precision
    """
    if not tick_size:
        return str(Decimal(price).quantize(TICK_FALLBACK, rounding=ROUND_DOWN))
    
    q = Decimal(str(price)).quantize(Decimal(str(tick_size)), rounding=ROUND_DOWN)
    return format(q, "f")


def build_order_params(
    *,
    symbol: str,
    side: str,  # BUY/SELL
    type_: str,  # LIMIT/MARKET/STOP/TAKE_PROFIT/STOP_MARKET/TAKE_PROFIT_MARKET
    qty: Optional[float],
    price: Optional[float],
    reduce_only: bool,
    close_order: bool,  # Is this a closing order (TP/SL/Close)
    hedge_hint: Optional[str],  # LONG/SHORT if known
    tick_size: Optional[str],
    time_in_force: Optional[str] = None,
) -> Dict:
    """
    Build safe order parameters that prevent -4061 and -1106 errors
    
    Key rules:
    - positionSide only if account is in Hedge Mode and we have a hint
    - reduceOnly only for supported order types and closing orders
    """
    params: Dict = {
        "symbol": symbol,
        "side": side,
        "type": type_
    }
    
    # positionSide only if Hedge Mode is active AND we have a hint
    if get_dual_position_mode() and hedge_hint:
        params["positionSide"] = hedge_hint  # "LONG" or "SHORT"
        logger.debug(f"Hedge Mode active, using positionSide={hedge_hint}")
    
    # Quantity
    if qty is not None:
        params["quantity"] = qty
    
    # Price (only for limit/stop orders)
    if price is not None and type_ in {"LIMIT", "STOP", "TAKE_PROFIT"}:
        params["price"] = quantize_price(price, tick_size)
    
    # Time in force (only for LIMIT orders)
    if time_in_force and type_ == "LIMIT":
        params["timeInForce"] = time_in_force
    
    # reduceOnly only for supported types AND closing orders (prevents -1106)
    supported_reduce = {"LIMIT", "STOP", "STOP_MARKET", "TAKE_PROFIT", "TAKE_PROFIT_MARKET"}
    if reduce_only and close_order and type_ in supported_reduce:
        params["reduceOnly"] = True
        logger.debug(f"reduceOnly=True for closing {type_} order")
    
    return params
