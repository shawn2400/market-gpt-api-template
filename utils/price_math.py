# -*- coding: utf-8 -*-
"""
Dynamic Price Math Utilities
Prevents negative prices and ensures proper tick size precision
"""
from __future__ import annotations
from decimal import Decimal, ROUND_DOWN
from typing import List
import logging

logger = logging.getLogger(__name__)


def clamp_price(v: float, min_tick: float) -> float:
    """Ensure price is never below minimum tick"""
    return max(v, float(min_tick))


def quantize(v: float, step: float) -> float:
    """Quantize value to step precision"""
    return float(Decimal(str(v)).quantize(Decimal(str(step)), rounding=ROUND_DOWN))


def tp_from_entry(
    side: str,
    entry: float,
    percents: List[float],
    tick: float = 0.0001
) -> List[float]:
    """
    Calculate TP levels from entry price based on percentage moves
    
    Args:
        side: "LONG" or "SHORT"
        entry: Entry price
        percents: List of percentage moves (e.g., [1.5, 2.5, 4.0, 6.0])
        tick: Tick size for precision
    
    Returns:
        List of TP prices (always positive, properly quantized)
    
    Example:
        >>> tp_from_entry("LONG", 43250.0, [1.5, 2.5, 4.0], 0.1)
        [43898.25, 44331.25, 44980.0]
    """
    out: List[float] = []
    
    for p in percents:
        k = float(p) / 100.0
        
        if side.upper() == "LONG":
            price = entry * (1.0 + k)
        else:
            price = entry * (1.0 - k)
        
        # Ensure price is never negative or zero
        price = clamp_price(price, tick)
        
        # Quantize to tick size
        price = quantize(price, tick)
        
        # Final safety check
        if price <= 0:
            logger.warning(f"Calculated TP price <= 0 ({price}), using min tick {tick}")
            price = tick
        
        out.append(price)
    
    return out


def sl_from_entry(
    side: str,
    entry: float,
    atr: float,
    multiplier: float = 1.5,
    tick: float = 0.0001
) -> float:
    """
    Calculate SL price from entry based on ATR
    
    Args:
        side: "LONG" or "SHORT"
        entry: Entry price
        atr: Average True Range value
        multiplier: ATR multiplier (default 1.5)
        tick: Tick size for precision
    
    Returns:
        SL price (always positive, properly quantized)
    """
    delta = abs(float(atr)) * float(multiplier)
    
    if side.upper() == "LONG":
        price = entry - delta
    else:
        price = entry + delta
    
    # Ensure price is valid
    price = clamp_price(price, tick)
    price = quantize(price, tick)
    
    if price <= 0:
        logger.warning(f"Calculated SL price <= 0 ({price}), using min tick {tick}")
        price = tick
    
    return price
