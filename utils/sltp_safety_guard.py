#!/usr/bin/env python3
"""
🛡️ SLTP Safety Guard - Prevents invalid orders from being sent
=====================================================

Validates SL/TP prices BEFORE attempting to place orders.
- SL must be > 0 AND logically correct for position side
- TP must be > 0 AND logically correct for position side
- If validation fails, returns explicit error (never sends bad order)
"""

import logging
from typing import Tuple, Optional

logger = logging.getLogger("algogpt.sltp_guard")


def validate_sl_price(
    symbol: str,
    sl_price: Optional[float],
    entry_price: float,
    position_side: str  # "LONG" or "SHORT"
) -> Tuple[bool, str]:
    """
    🛡️ Validate Stop Loss price is logically correct.
    
    Args:
        symbol: Trading pair
        sl_price: Stop loss price to validate
        entry_price: Position entry price
        position_side: "LONG" or "SHORT"
    
    Returns:
        (is_valid, error_message)
    
    Logic:
        LONG positions:  SL must be < entry_price AND > 0
        SHORT positions: SL must be > entry_price
    """
    # 🚨 CRITICAL: Check SL is not None/zero
    if sl_price is None:
        return False, f"SL is None"
    
    if not isinstance(sl_price, (int, float)):
        return False, f"SL is not numeric: {type(sl_price)}"
    
    # 🚨 CRITICAL: SL must ALWAYS be positive
    if sl_price <= 0:
        return False, f"SL={sl_price:.8f} <= 0 (INVALID for ANY position)"
    
    # 🚨 CRITICAL: Check SL is logically correct for position side
    if position_side == "LONG":
        # For LONG: SL must be < entry (below entry price)
        if sl_price >= entry_price:
            return False, f"LONG SL={sl_price:.8f} >= entry={entry_price:.8f} (SL must be BELOW entry)"
    
    elif position_side == "SHORT":
        # For SHORT: SL must be > entry (above entry price)
        if sl_price <= entry_price:
            return False, f"SHORT SL={sl_price:.8f} <= entry={entry_price:.8f} (SL must be ABOVE entry)"
    
    logger.debug(f"✅ SL validation passed: {symbol} {position_side} @ {entry_price:.8f}, SL @ {sl_price:.8f}")
    return True, ""


def validate_tp_price(
    symbol: str,
    tp_price: Optional[float],
    entry_price: float,
    position_side: str  # "LONG" or "SHORT"
) -> Tuple[bool, str]:
    """
    🛡️ Validate Take Profit price is logically correct.
    
    Args:
        symbol: Trading pair
        tp_price: Take profit price to validate
        entry_price: Position entry price
        position_side: "LONG" or "SHORT"
    
    Returns:
        (is_valid, error_message)
    
    Logic:
        LONG positions:  TP must be > entry_price
        SHORT positions: TP must be < entry_price
    """
    # 🚨 CRITICAL: Check TP is not None/zero
    if tp_price is None:
        return False, f"TP is None"
    
    if not isinstance(tp_price, (int, float)):
        return False, f"TP is not numeric: {type(tp_price)}"
    
    # 🚨 CRITICAL: TP must ALWAYS be positive
    if tp_price <= 0:
        return False, f"TP={tp_price:.8f} <= 0 (INVALID for ANY position)"
    
    # 🚨 CRITICAL: Check TP is logically correct for position side
    if position_side == "LONG":
        # For LONG: TP must be > entry (above entry price)
        if tp_price <= entry_price:
            return False, f"LONG TP={tp_price:.8f} <= entry={entry_price:.8f} (TP must be ABOVE entry)"
    
    elif position_side == "SHORT":
        # For SHORT: TP must be < entry (below entry price)
        if tp_price >= entry_price:
            return False, f"SHORT TP={tp_price:.8f} >= entry={entry_price:.8f} (TP must be BELOW entry)"
    
    logger.debug(f"✅ TP validation passed: {symbol} {position_side} @ {entry_price:.8f}, TP @ {tp_price:.8f}")
    return True, ""


def validate_sl_tp_pair(
    symbol: str,
    sl_price: Optional[float],
    tp_price: Optional[float],
    entry_price: float,
    position_side: str
) -> Tuple[bool, str]:
    """
    🛡️ Validate BOTH SL and TP together.
    
    Returns (is_valid, error_message)
    """
    # First validate SL
    sl_valid, sl_error = validate_sl_price(symbol, sl_price, entry_price, position_side)
    if not sl_valid:
        return False, f"SL validation failed: {sl_error}"
    
    # Then validate TP
    tp_valid, tp_error = validate_tp_price(symbol, tp_price, entry_price, position_side)
    if not tp_valid:
        return False, f"TP validation failed: {tp_error}"
    
    # Cross-check: SL and TP must be on opposite sides of entry
    if position_side == "LONG":
        # SL < entry < TP
        if not (sl_price < entry_price < tp_price):
            return False, f"LONG: Invalid order SL={sl_price:.8f} < Entry={entry_price:.8f} < TP={tp_price:.8f}"
    
    elif position_side == "SHORT":
        # TP < entry < SL
        if not (tp_price < entry_price < sl_price):
            return False, f"SHORT: Invalid order TP={tp_price:.8f} < Entry={entry_price:.8f} < SL={sl_price:.8f}"
    
    logger.info(f"✅ SL/TP pair validation passed: {symbol} {position_side} SL/Entry/TP = {sl_price:.8f}/{entry_price:.8f}/{tp_price:.8f}")
    return True, ""


def safe_create_order(
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    price: Optional[float],
    stop_price: Optional[float],
    position_side: str,
    entry_price: float,
    client_order_id: str,
    logger_obj
) -> Tuple[bool, str]:
    """
    🛡️ Safe order creation wrapper.
    
    Validates SL/TP BEFORE sending to Binance.
    Never sends an order with invalid prices.
    
    Returns: (should_proceed, error_message)
    """
    # For STOP orders (SL), validate stop_price
    if order_type == "STOP_MARKET" and stop_price is not None:
        is_valid, error = validate_sl_price(symbol, stop_price, entry_price, position_side)
        if not is_valid:
            logger_obj.error(f"🛡️ BLOCKED INVALID SL ORDER: {symbol} {error}")
            return False, error
    
    # For TAKE_PROFIT orders, validate price
    if order_type == "TAKE_PROFIT_MARKET" and price is not None:
        is_valid, error = validate_tp_price(symbol, price, entry_price, position_side)
        if not is_valid:
            logger_obj.error(f"🛡️ BLOCKED INVALID TP ORDER: {symbol} {error}")
            return False, error
    
    return True, ""


__all__ = [
    "validate_sl_price",
    "validate_tp_price",
    "validate_sl_tp_pair",
    "safe_create_order",
]
