#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Budget Validator - Enforce $25 minimum BEFORE leverage application
==================================================================
Critical safeguard: No trade can be less than $25 USDT before leverage is applied.
This prevents dust positions and ensures meaningful P&L.
"""

import logging
import os
from typing import Tuple

logger = logging.getLogger("budget_validator")

# $25 minimum per trade - hardcoded as safety
MINIMUM_TRADE_USDT = 25.0

# Max budget per trade (before leverage)
MAXIMUM_TRADE_USDT = float(os.getenv("BUDGET_MAX_USDT", "1000.0"))


def validate_budget_before_leverage(budget_usdt: float, quality_score: float = 7.0) -> Tuple[bool, float, str]:
    """
    Validate that budget meets minimum requirements BEFORE any leverage is applied.
    
    Args:
        budget_usdt: Proposed budget in USDT (before leverage)
        quality_score: Trade quality score (5-10) for dynamic adjustment
        
    Returns:
        Tuple of (is_valid, adjusted_budget, reason)
    """
    if budget_usdt is None or budget_usdt <= 0:
        return False, 0.0, f"❌ Invalid budget: {budget_usdt}"
    
    # HARD MINIMUM: $25 USDT
    if budget_usdt < MINIMUM_TRADE_USDT:
        reason = f"❌ Budget ${budget_usdt:.2f} < minimum ${MINIMUM_TRADE_USDT:.2f}"
        logger.warning(reason)
        return False, 0.0, reason
    
    # Hard maximum
    if budget_usdt > MAXIMUM_TRADE_USDT:
        adjusted = MAXIMUM_TRADE_USDT
        reason = f"⚠️ Budget capped: ${budget_usdt:.2f} → ${adjusted:.2f}"
        logger.info(reason)
        return True, adjusted, reason
    
    # Quality-based adjustment
    if quality_score < 5.0:
        # Low quality - cannot trade
        return False, 0.0, f"❌ Quality too low ({quality_score:.1f} < 5.0)"
    elif quality_score < 7.0:
        # Medium quality - minimum $25 only
        if budget_usdt < MINIMUM_TRADE_USDT:
            return False, 0.0, f"❌ Quality {quality_score:.1f}: need min ${MINIMUM_TRADE_USDT}"
        return True, budget_usdt, "✅ Approved (medium quality)"
    else:
        # High quality - allow full range
        return True, budget_usdt, "✅ Approved (high quality)"


def enforce_minimum_trade_size(budget_usdt: float) -> float:
    """
    Enforce minimum trade size. If below $25, round up to $25.
    
    Args:
        budget_usdt: Proposed budget
        
    Returns:
        Adjusted budget (minimum $25)
    """
    if budget_usdt < MINIMUM_TRADE_USDT:
        logger.info(f"🔧 Budget adjusted: ${budget_usdt:.2f} → ${MINIMUM_TRADE_USDT:.2f}")
        return MINIMUM_TRADE_USDT
    return budget_usdt


def check_leverage_budget_compatibility(budget_usdt: float, leverage: float, max_notional: float) -> Tuple[bool, str]:
    """
    Validate that leverage * budget doesn't exceed notional limits.
    
    Args:
        budget_usdt: Budget BEFORE leverage
        leverage: Applied leverage (e.g., 5.0)
        max_notional: Max notional value allowed by Binance
        
    Returns:
        Tuple of (is_valid, reason)
    """
    notional_value = budget_usdt * leverage
    
    if notional_value > max_notional:
        reason = f"❌ Notional ${notional_value:.2f} > max ${max_notional:.2f} @ {leverage}x"
        logger.warning(reason)
        return False, reason
    
    return True, f"✅ Notional OK: ${notional_value:.2f} @ {leverage}x"


def validate_full_trade_params(budget_usdt: float, leverage: float, 
                               quality_score: float, max_notional: float) -> Tuple[bool, float, str]:
    """
    Complete validation: budget → leverage → notional.
    
    Returns:
        Tuple of (is_valid, final_budget, reason)
    """
    # Step 1: Check minimum budget
    is_valid, final_budget, reason1 = validate_budget_before_leverage(budget_usdt, quality_score)
    if not is_valid:
        return False, 0.0, reason1
    
    # Step 2: Check leverage compatibility
    is_valid, reason2 = check_leverage_budget_compatibility(final_budget, leverage, max_notional)
    if not is_valid:
        return False, 0.0, reason2
    
    logger.info(f"✅ Trade validated: ${final_budget:.2f} @ {leverage}x = ${final_budget * leverage:.2f} notional")
    return True, final_budget, f"✅ Approved: {reason1} | {reason2}"
