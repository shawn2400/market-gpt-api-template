#!/usr/bin/env python3
"""
Trailing TP System - Shared Module
Tracks peak prices and automatically closes positions when price drops from peak
"""
import os
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

# 🎯 TRAILING TP CONFIGURATION
ENABLE_TRAILING_TP = os.getenv("ENABLE_TRAILING_TP", "1").lower() in ("1", "true", "yes")
TRAILING_ACTIVATION_PCT = float(os.getenv("TRAILING_ACTIVATION_PCT", "25.0"))
TRAILING_DISTANCE_PCT = float(os.getenv("TRAILING_DISTANCE_PCT", "15.0"))

# Global state - tracks peak prices and trailing state per symbol
_trailing_positions: Dict[str, Dict[str, Any]] = {}


def calculate_pnl_percent(entry_price: float, current_price: float, side: str) -> float:
    """Calculate PNL percentage based on position side"""
    if entry_price <= 0:
        return 0.0
    
    if side == "LONG":
        return ((current_price - entry_price) / entry_price) * 100
    else:  # SHORT
        return ((entry_price - current_price) / entry_price) * 100


def should_activate_trailing(position: Dict[str, Any]) -> bool:
    """Check if trailing TP should be activated for this position"""
    symbol = position.get("symbol", "")
    
    if symbol in _trailing_positions:
        return False
    
    entry = float(position.get("entryPrice", 0))
    mark = float(position.get("markPrice", 0))
    amt = float(position.get("positionAmt", 0))
    
    if entry <= 0 or mark <= 0:
        return False
    
    side = "LONG" if amt > 0 else "SHORT"
    pnl_pct = calculate_pnl_percent(entry, mark, side)
    
    return pnl_pct >= TRAILING_ACTIVATION_PCT


def activate_trailing(position: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activate trailing TP for a position
    Returns: trailing_data dict for notification
    """
    symbol = position.get("symbol", "")
    entry = float(position.get("entryPrice", 0))
    mark = float(position.get("markPrice", 0))
    amt = float(position.get("positionAmt", 0))
    side = "LONG" if amt > 0 else "SHORT"
    
    pnl_pct = calculate_pnl_percent(entry, mark, side)
    
    trailing_data = {
        "peak_price": mark,
        "activation_time": datetime.now(timezone.utc),
        "trailing_distance": TRAILING_DISTANCE_PCT,
        "entry_price": entry,
        "side": side,
        "activation_pnl": pnl_pct,
        "symbol": symbol
    }
    
    _trailing_positions[symbol] = trailing_data
    
    logger.info(f"🎯 Trailing TP activated for {symbol} | PNL: +{pnl_pct:.1f}% | Peak: {mark:.4f}")
    
    return trailing_data


def update_trailing_peak(position: Dict[str, Any]) -> None:
    """Update peak price if new high/low reached"""
    symbol = position.get("symbol", "")
    if symbol not in _trailing_positions:
        return
    
    trailing_data = _trailing_positions[symbol]
    mark = float(position.get("markPrice", 0))
    peak = trailing_data["peak_price"]
    side = trailing_data["side"]
    
    if side == "LONG" and mark > peak:
        old_peak = peak
        trailing_data["peak_price"] = mark
        logger.info(f"📈 {symbol}: New peak {mark:.4f} (was {old_peak:.4f})")
    elif side == "SHORT" and mark < peak:
        old_peak = peak
        trailing_data["peak_price"] = mark
        logger.info(f"📉 {symbol}: New peak {mark:.4f} (was {old_peak:.4f})")


def should_close_by_trailing(position: Dict[str, Any]) -> Tuple[bool, float, str, Dict[str, Any]]:
    """
    Check if position should be closed based on trailing TP logic
    Returns: (should_close, current_pnl_pct, reason, trailing_data)
    """
    symbol = position.get("symbol", "")
    if symbol not in _trailing_positions:
        return False, 0.0, "", {}
    
    trailing_data = _trailing_positions[symbol]
    mark = float(position.get("markPrice", 0))
    peak = trailing_data["peak_price"]
    side = trailing_data["side"]
    entry = trailing_data["entry_price"]
    
    if peak <= 0 or mark <= 0:
        return False, 0.0, "", {}
    
    if side == "LONG":
        drawdown_pct = abs((peak - mark) / peak) * 100
    else:  # SHORT
        drawdown_pct = abs((mark - peak) / peak) * 100
    
    current_pnl = calculate_pnl_percent(entry, mark, side)
    
    if drawdown_pct >= TRAILING_DISTANCE_PCT:
        direction = "dropped" if side == "LONG" else "rose"
        reason = f"Price {direction} {drawdown_pct:.1f}% from peak {peak:.4f}"
        logger.info(f"🎯 {symbol} trailing close triggered: {reason} | Current PNL: +{current_pnl:.1f}%")
        return True, current_pnl, reason, trailing_data
    
    return False, current_pnl, "", {}


def remove_trailing(symbol: str) -> Dict[str, Any]:
    """
    Remove symbol from trailing tracking
    Returns: trailing_data for notification
    """
    return _trailing_positions.pop(symbol, {})


def get_trailing_data(symbol: str) -> Dict[str, Any]:
    """Get trailing data for a symbol"""
    return _trailing_positions.get(symbol, {})


def get_all_trailing_symbols() -> list:
    """Get list of all symbols currently in trailing mode"""
    return list(_trailing_positions.keys())


def is_enabled() -> bool:
    """Check if trailing TP is enabled"""
    return ENABLE_TRAILING_TP
