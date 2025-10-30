# utils/portfolio_manager.py
"""
Smart Portfolio Manager - Budget & Leverage Allocation
Splits wallet across 2-5 concurrent trades based on quality scores
"""
import os
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("algogpt.portfolio")

# Configuration
MAX_CONCURRENT_TRADES = int(os.getenv("MAX_CONCURRENT_TRADES", "4"))
MIN_BUDGET_PER_TRADE_USDT = float(os.getenv("MIN_BUDGET_PER_TRADE_USDT", "20"))
MAX_BUDGET_PER_TRADE_USDT = float(os.getenv("MAX_BUDGET_PER_TRADE_USDT", "200"))
TOTAL_WALLET_ALLOCATION_PCT = float(os.getenv("TOTAL_WALLET_ALLOCATION_PCT", "80"))  # Use 80% of wallet

# Score-based leverage multipliers
SCORE_LEVERAGE_MAP = {
    9.0: 1.5,   # Score >= 9.0 → 1.5x leverage boost
    8.0: 1.3,   # Score >= 8.0 → 1.3x leverage boost
    7.0: 1.1,   # Score >= 7.0 → 1.1x leverage boost
    6.0: 1.0,   # Score >= 6.0 → normal leverage
}

def get_leverage_multiplier(score: float) -> float:
    """
    Returns leverage multiplier based on quality score
    Higher score = more leverage
    """
    for threshold, mult in sorted(SCORE_LEVERAGE_MAP.items(), reverse=True):
        if score >= threshold:
            return mult
    return 0.8  # Below 6.0 → reduce leverage

def calculate_score_based_leverage(base_leverage: int, score: float, max_lev: int = 20) -> int:
    """
    Calculate leverage based on trade quality score
    
    Args:
        base_leverage: Base leverage (e.g., 10)
        score: Quality score (0-10)
        max_lev: Maximum allowed leverage
    
    Returns:
        Adjusted leverage
    """
    multiplier = get_leverage_multiplier(score)
    adjusted = int(base_leverage * multiplier)
    return min(adjusted, max_lev)

def get_available_wallet_balance() -> float:
    """
    Get available USDT balance from Binance
    """
    try:
        try:
            from utils.binance_client import init_client as get_client
        except:
            from utils.binance_client import _init_client as get_client
        
        client = get_client()
        if not client:
            return 0.0
        
        # Get Futures USDT balance
        account = client.futures_account()
        for asset in account.get("assets", []):
            if asset.get("asset") == "USDT":
                return float(asset.get("availableBalance", 0))
        
        return 0.0
    except Exception as e:
        logger.error(f"Failed to get wallet balance: {e}")
        return 0.0

def get_active_trades_count() -> int:
    """
    Count currently active trades
    """
    try:
        try:
            from utils.binance_client import init_client as get_client
        except:
            from utils.binance_client import _init_client as get_client
        
        try:
            from utils.binance_client import get_all_positions
        except:
            def get_all_positions(client):
                return client.futures_position_information() if client else []
        
        client = get_client()
        if not client:
            return 0
        
        positions = get_all_positions(client)
        active = [p for p in positions if abs(float(p.get("positionAmt", 0))) > 0]
        return len(active)
    except Exception as e:
        logger.error(f"Failed to count active trades: {e}")
        return 0

def calculate_trade_budget(
    score: float,
    available_balance: Optional[float] = None,
    active_count: Optional[int] = None
) -> Dict[str, Any]:
    """
    Calculate smart budget allocation for a trade
    
    Rules:
    1. Higher score trades get larger allocation
    2. Don't exceed MAX_CONCURRENT_TRADES
    3. Reserve enough budget for additional trades
    4. Respect min/max budget limits
    
    Args:
        score: Trade quality score (0-10)
        available_balance: Override available balance (for testing)
        active_count: Override active trades count (for testing)
    
    Returns:
        Dict with budget_usdt and allocation_pct
    """
    # Get current state
    if available_balance is None:
        available_balance = get_available_wallet_balance()
    
    if active_count is None:
        active_count = get_active_trades_count()
    
    # Calculate allocatable funds
    total_allocatable = available_balance * (TOTAL_WALLET_ALLOCATION_PCT / 100.0)
    
    # Check if we can take more trades
    if active_count >= MAX_CONCURRENT_TRADES:
        return {
            "ok": False,
            "reason": "max_concurrent_trades_reached",
            "budget_usdt": 0.0,
            "max_trades": MAX_CONCURRENT_TRADES,
            "active_trades": active_count
        }
    
    # Calculate base budget (equal split)
    slots_available = MAX_CONCURRENT_TRADES - active_count
    base_budget = total_allocatable / MAX_CONCURRENT_TRADES
    
    # Apply score-based boost
    # Score 9+ gets 1.4x base, Score 8+ gets 1.2x, Score 7+ gets 1.0x
    if score >= 9.0:
        score_mult = 1.4
    elif score >= 8.0:
        score_mult = 1.2
    elif score >= 7.0:
        score_mult = 1.0
    elif score >= 6.0:
        score_mult = 0.8
    else:
        score_mult = 0.6
    
    budget = base_budget * score_mult
    
    # Enforce limits
    budget = max(MIN_BUDGET_PER_TRADE_USDT, min(budget, MAX_BUDGET_PER_TRADE_USDT))
    budget = min(budget, total_allocatable)  # Don't exceed available
    
    allocation_pct = (budget / available_balance * 100) if available_balance > 0 else 0
    
    return {
        "ok": True,
        "budget_usdt": round(budget, 2),
        "allocation_pct": round(allocation_pct, 2),
        "available_balance": round(available_balance, 2),
        "active_trades": active_count,
        "slots_remaining": slots_available,
        "score_multiplier": score_mult
    }

def should_accept_trade(score: float, min_score: float = 7.0) -> tuple[bool, str]:
    """
    Determine if trade should be accepted based on portfolio state
    
    Returns:
        (accept: bool, reason: str)
    """
    # Check score
    if score < min_score:
        return False, f"score_too_low (< {min_score})"
    
    # Check concurrent trades
    active_count = get_active_trades_count()
    if active_count >= MAX_CONCURRENT_TRADES:
        return False, f"max_concurrent_reached ({active_count}/{MAX_CONCURRENT_TRADES})"
    
    # Check available balance
    balance = get_available_wallet_balance()
    if balance < MIN_BUDGET_PER_TRADE_USDT:
        return False, f"insufficient_balance (${balance:.2f} < ${MIN_BUDGET_PER_TRADE_USDT})"
    
    return True, "ok"

__all__ = [
    "calculate_score_based_leverage",
    "calculate_trade_budget",
    "should_accept_trade",
    "get_available_wallet_balance",
    "get_active_trades_count"
]
