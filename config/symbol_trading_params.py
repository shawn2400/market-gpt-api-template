#!/usr/bin/env python3
"""
Symbol-Specific Trading Parameters
Realistic trading constraints per coin type based on performance data
"""
import os
from typing import Dict, Any

# TRX - Stability Coin (frequent false breakouts)
SYMBOL_CONFIG = {
    'TRXUSDT': {
        'max_trades_per_6h': 1,
        'min_holding_minutes': 45,
        'max_holding_minutes': 180,
        'cooldown_after_loss_minutes': 120,
        'min_quality_threshold': 6.5,
        'position_size_multiplier': 0.8,  # 20% smaller
        'description': 'Stable coin - limit frequency'
    },
    
    # High Volatility Memecoins (1000XECUSDT, 1000RATSUSDT, A2ZUSDT)
    '1000XECUSDT': {
        'max_trades_per_6h': 2,
        'min_holding_minutes': 15,
        'max_holding_minutes': 90,
        'cooldown_after_loss_minutes': 60,
        'min_quality_threshold': 6.0,
        'position_size_multiplier': 1.3,  # 30% boost for proven pattern
        'pattern_boost_enabled': True,
        'description': 'High vol memecoin - proven pattern'
    },
    
    '1000RATSUSDT': {
        'max_trades_per_6h': 2,
        'min_holding_minutes': 15,
        'max_holding_minutes': 90,
        'cooldown_after_loss_minutes': 60,
        'min_quality_threshold': 6.0,
        'position_size_multiplier': 1.2,  # 20% boost
        'pattern_boost_enabled': True,
        'description': 'High vol memecoin - proven pattern'
    },
    
    'A2ZUSDT': {
        'max_trades_per_6h': 2,
        'min_holding_minutes': 20,
        'max_holding_minutes': 120,
        'cooldown_after_loss_minutes': 60,
        'min_quality_threshold': 6.0,
        'position_size_multiplier': 1.15,  # 15% boost
        'pattern_boost_enabled': True,
        'description': 'Micro cap - proven pattern'
    },
    
    # Standard altcoins (default behavior)
    'DEFAULT': {
        'max_trades_per_6h': 3,
        'min_holding_minutes': 30,
        'max_holding_minutes': 240,
        'cooldown_after_loss_minutes': 45,
        'min_quality_threshold': 5.5,
        'position_size_multiplier': 1.0,
        'pattern_boost_enabled': False,
        'description': 'Standard altcoin'
    }
}

def get_symbol_config(symbol: str) -> Dict[str, Any]:
    """Get config for symbol, fallback to DEFAULT"""
    return SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG['DEFAULT'])

def apply_holding_time_constraint(
    symbol: str,
    current_hold_minutes: float,
    is_profitable: bool
) -> bool:
    """
    Check if position should be held based on symbol-specific constraints
    
    Args:
        symbol: Trading symbol
        current_hold_minutes: How long position has been held
        is_profitable: Is position currently profitable
        
    Returns:
        True = continue holding, False = close position
    """
    config = get_symbol_config(symbol)
    min_hold = config.get('min_holding_minutes', 30)
    max_hold = config.get('max_holding_minutes', 240)
    
    # Never close before minimum hold time
    if current_hold_minutes < min_hold:
        return True
    
    # Always close after maximum hold time
    if current_hold_minutes > max_hold:
        return False
    
    # For profitable positions, can close anytime after min_hold
    if is_profitable:
        return False  # Allow closure
    
    # For unprofitable positions, use max_hold as hard limit
    return True

def get_position_size_multiplier(
    symbol: str,
    pattern_confidence: float = 0.0
) -> float:
    """
    Get position size multiplier for symbol
    
    Args:
        symbol: Trading symbol
        pattern_confidence: Pattern win rate (0.0-1.0) if applicable
        
    Returns:
        Multiplier to apply to base position size
    """
    config = get_symbol_config(symbol)
    base_multiplier = config.get('position_size_multiplier', 1.0)
    
    # Add extra boost if pattern is very proven
    if config.get('pattern_boost_enabled', False) and pattern_confidence > 0.70:
        return base_multiplier * 1.1  # Additional 10% boost
    
    return base_multiplier

def check_trade_frequency_limit(
    symbol: str,
    recent_trades_6h: int
) -> bool:
    """
    Check if symbol has hit max trades per 6 hours
    
    Args:
        symbol: Trading symbol
        recent_trades_6h: Number of trades in last 6 hours
        
    Returns:
        True = can trade, False = at limit
    """
    config = get_symbol_config(symbol)
    max_trades = config.get('max_trades_per_6h', 3)
    return recent_trades_6h < max_trades

if __name__ == "__main__":
    # Test the config
    print("📊 Symbol Trading Parameters Test:\n")
    for symbol in ['TRXUSDT', '1000XECUSDT', 'BTCUSDT', 'RANDOM']:
        cfg = get_symbol_config(symbol)
        print(f"✅ {symbol}:")
        print(f"   Max trades/6h: {cfg['max_trades_per_6h']}")
        print(f"   Min hold: {cfg['min_holding_minutes']} min")
        print(f"   Position size: {cfg['position_size_multiplier']:.1%} of base")
        print(f"   {cfg['description']}\n")
