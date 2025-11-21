#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚀 MAX HOLDING POWER - Dynamic Position Management System
========================================================
Manages position states dynamically and optimizes SL/TP based on market conditions.
EARLY_PROFIT → STRONG_TREND → CONSOLIDATION → MATURE_PROFIT → EXTREME_PROFIT
"""

import logging
import time
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from datetime import datetime

logger = logging.getLogger("max_holding_power")


class PositionState(Enum):
    """5-level dynamic position states"""
    EARLY_PROFIT = "early_profit"
    STRONG_TREND = "strong_trend"
    CONSOLIDATION = "consolidation"
    MATURE_PROFIT = "mature_profit"
    EXTREME_PROFIT = "extreme_profit"


@dataclass
class DynamicPosition:
    """Tracks position metrics and state transitions"""
    symbol: str
    entry_price: float
    current_price: float
    quantity: float
    direction: str  # LONG or SHORT
    position_state: PositionState = PositionState.EARLY_PROFIT
    
    # Dynamic metrics
    momentum_strength: float = 0.0
    trend_quality: float = 0.0
    volatility_score: float = 0.0
    volume_confirmation: float = 0.0
    
    # Performance tracking
    unrealized_pnl: float = 0.0
    pnl_percentage: float = 0.0
    time_in_trade: float = 0.0
    max_favorable_move: float = 0.0


class MaxHoldingPowerManager:
    """Main manager for dynamic position holding power"""
    
    def __init__(self):
        self.active_positions: Dict[str, DynamicPosition] = {}
        self.state_config = {
            'EARLY_PROFIT': {
                'min_pnl': 0.02,
                'min_momentum': 0.6,
                'min_trend': 0.6,
                'min_volume': 1.2,
                'sl_distance': 0.01,  # 1% from entry
                'tp_extension': 1.0
            },
            'STRONG_TREND': {
                'min_pnl': 0.05,
                'min_momentum': 0.7,
                'min_trend': 0.7,
                'min_volume': 1.5,
                'sl_distance': 0.03,  # 3% trailing
                'tp_extension': 1.2
            },
            'CONSOLIDATION': {
                'min_pnl': 0.02,
                'min_momentum': 0.6,
                'min_trend': 0.6,
                'min_volume': 1.2,
                'sl_distance': 0.02,  # 2% tight
                'tp_extension': 1.1
            },
            'MATURE_PROFIT': {
                'min_pnl': 0.10,
                'min_momentum': 0.8,
                'min_trend': 0.8,
                'min_volume': 2.0,
                'sl_distance': 0.05,  # 5% loose
                'tp_extension': 1.3
            },
            'EXTREME_PROFIT': {
                'min_pnl': 0.20,
                'min_momentum': 0.9,
                'min_trend': 0.9,
                'min_volume': 2.5,
                'sl_distance': 0.10,  # 10% very loose
                'tp_extension': 1.5
            }
        }
        logger.info("✅ MAX HOLDING POWER Manager initialized")
    
    def register_position(self, symbol: str, entry_price: float, 
                         current_price: float, quantity: float, 
                         direction: str) -> None:
        """Register a new position for tracking"""
        pos = DynamicPosition(
            symbol=symbol,
            entry_price=entry_price,
            current_price=current_price,
            quantity=quantity,
            direction=direction
        )
        self.active_positions[symbol] = pos
        logger.info(f"📊 Registered: {symbol} | Entry: {entry_price:.8f} | Dir: {direction}")
    
    def update_position_metrics(self, symbol: str, current_price: float,
                               momentum: float, trend_quality: float,
                               volatility: float, volume_conf: float) -> None:
        """Update position metrics"""
        if symbol not in self.active_positions:
            return
        
        pos = self.active_positions[symbol]
        pos.current_price = current_price
        pos.momentum_strength = momentum
        pos.trend_quality = trend_quality
        pos.volatility_score = volatility
        pos.volume_confirmation = volume_conf
        
        # Calculate PNL
        if pos.direction == "LONG":
            pos.unrealized_pnl = (current_price - pos.entry_price) * pos.quantity
            pos.pnl_percentage = (current_price - pos.entry_price) / pos.entry_price
        else:
            pos.unrealized_pnl = (pos.entry_price - current_price) * pos.quantity
            pos.pnl_percentage = (pos.entry_price - current_price) / pos.entry_price
        
        # Track max favorable move
        if pos.pnl_percentage > pos.max_favorable_move:
            pos.max_favorable_move = pos.pnl_percentage
    
    def determine_position_state(self, symbol: str) -> Optional[PositionState]:
        """Determine current state based on metrics"""
        if symbol not in self.active_positions:
            return None
        
        pos = self.active_positions[symbol]
        
        # Check EXTREME_PROFIT
        if (pos.pnl_percentage >= 0.20 and 
            pos.momentum_strength >= 0.9 and 
            pos.trend_quality >= 0.9 and 
            pos.volume_confirmation >= 2.5):
            return PositionState.EXTREME_PROFIT
        
        # Check MATURE_PROFIT
        if (pos.pnl_percentage >= 0.10 and 
            pos.momentum_strength >= 0.8 and 
            pos.trend_quality >= 0.8 and 
            pos.volume_confirmation >= 2.0):
            return PositionState.MATURE_PROFIT
        
        # Check STRONG_TREND
        if (pos.pnl_percentage >= 0.05 and 
            pos.momentum_strength >= 0.7 and 
            pos.trend_quality >= 0.7 and 
            pos.volume_confirmation >= 1.5):
            return PositionState.STRONG_TREND
        
        # Check CONSOLIDATION
        if (pos.pnl_percentage >= 0.02 and 
            pos.momentum_strength >= 0.6 and 
            pos.trend_quality >= 0.6 and 
            pos.volume_confirmation >= 1.2):
            return PositionState.CONSOLIDATION
        
        return PositionState.EARLY_PROFIT
    
    def get_holding_confidence(self, symbol: str) -> float:
        """Calculate confidence in holding this position (0-1)"""
        if symbol not in self.active_positions:
            return 0.0
        
        pos = self.active_positions[symbol]
        scores = [
            pos.momentum_strength * 0.30,  # 30%
            pos.trend_quality * 0.25,      # 25%
            pos.volume_confirmation * 0.20, # 20%
            pos.volatility_score * 0.15,   # 15%
            min(1.0, pos.time_in_trade / 7200) * 0.10  # 10% (2h max)
        ]
        return sum(scores)
    
    def get_sl_tp_adjustments(self, symbol: str) -> Optional[Tuple[float, float]]:
        """Get recommended SL and TP adjustments based on state"""
        if symbol not in self.active_positions:
            return None
        
        pos = self.active_positions[symbol]
        state = pos.position_state
        config = self.state_config[state.value.upper()]
        
        # Calculate new SL and TP based on current price and state config
        if pos.direction == "LONG":
            new_sl = pos.current_price * (1 - config['sl_distance'])
            new_tp = pos.current_price * (1 + config['tp_extension'] * 0.1)
        else:  # SHORT
            new_sl = pos.current_price * (1 + config['sl_distance'])
            new_tp = pos.current_price * (1 - config['tp_extension'] * 0.1)
        
        return (new_sl, new_tp)
    
    def should_add_to_position(self, symbol: str) -> bool:
        """Check if conditions warrant adding to position"""
        if symbol not in self.active_positions:
            return False
        
        pos = self.active_positions[symbol]
        return (pos.position_state in [PositionState.STRONG_TREND, PositionState.MATURE_PROFIT] and
                self.get_holding_confidence(symbol) >= 0.8 and
                pos.pnl_percentage >= 0.05)
    
    def should_early_exit(self, symbol: str) -> bool:
        """Check if early exit conditions are met"""
        if symbol not in self.active_positions:
            return False
        
        pos = self.active_positions[symbol]
        return (pos.momentum_strength <= 0.3 and 
                pos.volume_confirmation <= 0.8 and
                pos.pnl_percentage < 0.02)
    
    def get_position_report(self, symbol: str) -> Optional[Dict]:
        """Get detailed position report"""
        if symbol not in self.active_positions:
            return None
        
        pos = self.active_positions[symbol]
        confidence = self.get_holding_confidence(symbol)
        
        return {
            'symbol': symbol,
            'direction': pos.direction,
            'entry_price': pos.entry_price,
            'current_price': pos.current_price,
            'pnl_pct': f"{pos.pnl_percentage * 100:.2f}%",
            'state': pos.position_state.value,
            'confidence': f"{confidence:.2f}",
            'momentum': f"{pos.momentum_strength:.2f}",
            'trend_quality': f"{pos.trend_quality:.2f}",
            'volume_conf': f"{pos.volume_confirmation:.2f}"
        }


# Singleton instance
_manager: Optional[MaxHoldingPowerManager] = None


def get_max_holding_manager() -> MaxHoldingPowerManager:
    """Get singleton manager instance"""
    global _manager
    if _manager is None:
        _manager = MaxHoldingPowerManager()
    return _manager
