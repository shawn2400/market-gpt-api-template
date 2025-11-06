# -*- coding: utf-8 -*-
"""
Precision Utilities for Binance Futures
Handles tick size and step size rounding for price and quantity.
"""
import math
import logging

log = logging.getLogger(__name__)


def quantize_price(price: float, tick_size: float) -> float:
    """
    Round price down to nearest tick_size.
    
    Args:
        price: Raw price
        tick_size: Binance tick size (e.g., 0.01, 0.1)
        
    Returns:
        Quantized price
    """
    if tick_size <= 0:
        return price
    return math.floor(price / tick_size) * tick_size


def quantize_qty(qty: float, step_size: float) -> float:
    """
    Round quantity down to nearest step_size.
    
    Args:
        qty: Raw quantity
        step_size: Binance step size (e.g., 0.001, 1.0)
        
    Returns:
        Quantized quantity
    """
    if step_size <= 0:
        return qty
    return math.floor(qty / step_size) * step_size


def near(a: float, b: float, eps: float = 1e-9) -> bool:
    """
    Check if two floats are nearly equal.
    
    Args:
        a: First value
        b: Second value
        eps: Epsilon tolerance
        
    Returns:
        True if values are within epsilon
    """
    return abs(a - b) <= eps * max(1.0, abs(a), abs(b))
