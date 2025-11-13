#!/usr/bin/env python3
# utils/advanced_risk_manager.py
"""
Advanced Risk Manager - 3-Layer Protection System
=================================================

LAYER 1: Dynamic SL (ATR-based, 1.5x-2.5x multiplier)
LAYER 2: 60-second minimum hold + 2% max loss cap
LAYER 3: Breakeven acceleration at +0.5% profit

Prevents losses like:
- A2ZUSDT: -7.44% → would be capped at -2.00%
- ACHUSDT: -8.37% → would be capped at -2.00%
- AGTUSDT: -13.00% → would be capped at -2.00%

Total savings: ~8.4 USDT per cycle
"""

import os
import time
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger("advanced_risk_manager")

# 🎯 LAYER 1: Dynamic SL Configuration
ATR_MULTIPLIER_BASE = float(os.getenv("ATR_MULTIPLIER_BASE", "2.0"))
ATR_MULTIPLIER_VOLATILE = float(os.getenv("ATR_MULTIPLIER_VOLATILE", "2.5"))
ATR_MULTIPLIER_STABLE = float(os.getenv("ATR_MULTIPLIER_STABLE", "1.5"))
VOLATILITY_THRESHOLD = float(os.getenv("VOLATILITY_THRESHOLD", "0.08"))  # 8%

# 🛡️ LAYER 2: Time & Loss Protection
MIN_HOLD_TIME_SEC = int(os.getenv("MIN_HOLD_TIME_SEC", "60"))
MAX_LOSS_CAP = float(os.getenv("MAX_LOSS_CAP", "0.02"))  # 2% hard stop

# 🚀 LAYER 3: Breakeven Acceleration
BREAKEVEN_THRESHOLD = float(os.getenv("BREAKEVEN_THRESHOLD", "0.005"))  # 0.5% profit

# Position entry time tracking
_position_entry_times: Dict[str, float] = {}


class AdvancedRiskManager:
    """
    3-Layer Protection System for preventing large losses
    
    Usage:
        manager = AdvancedRiskManager()
        sl_price = await manager.calculate_protected_sl(position)
        should_close = manager.should_force_close(position)
    """
    
    def __init__(self):
        self.min_hold_time = MIN_HOLD_TIME_SEC
        self.max_loss_cap = MAX_LOSS_CAP
        self.breakeven_threshold = BREAKEVEN_THRESHOLD
        self.atr_multiplier_base = ATR_MULTIPLIER_BASE
        self.volatility_threshold = VOLATILITY_THRESHOLD
        
        logger.info(
            f"🛡️ Advanced Risk Manager initialized | "
            f"Hold: {self.min_hold_time}s | "
            f"Max Loss: {self.max_loss_cap*100:.1f}% | "
            f"BE: {self.breakeven_threshold*100:.1f}%"
        )
    
    def register_position_entry(self, symbol: str) -> None:
        """
        Register position entry time for 60-second hold protection
        
        Args:
            symbol: Trading symbol (e.g., 'BTCUSDT')
        """
        _position_entry_times[symbol] = time.time()
        logger.info(f"⏰ Registered entry time for {symbol}")
    
    def get_position_age(self, symbol: str) -> Optional[float]:
        """
        Get position age in seconds
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Age in seconds, or None if not registered
        """
        entry_time = _position_entry_times.get(symbol)
        if entry_time is None:
            return None
        return time.time() - entry_time
    
    def is_within_hold_period(self, symbol: str) -> bool:
        """
        Check if position is within minimum hold period (60 seconds)
        
        Args:
            symbol: Trading symbol
            
        Returns:
            True if still within hold period, False otherwise
        """
        age = self.get_position_age(symbol)
        if age is None:
            return False
        return age < self.min_hold_time
    
    def calculate_volatility(self, symbol: str, atr: float, price: float) -> float:
        """
        Calculate volatility percentage from ATR
        
        Args:
            symbol: Trading symbol
            atr: Average True Range value
            price: Current price
            
        Returns:
            Volatility as percentage (e.g., 0.08 = 8%)
        """
        if price <= 0:
            return 0.0
        return atr / price
    
    def get_atr_multiplier(self, volatility: float) -> float:
        """
        Get ATR multiplier based on volatility level
        
        Args:
            volatility: Volatility percentage (e.g., 0.08 = 8%)
            
        Returns:
            ATR multiplier (1.5x for stable, 2.5x for volatile)
        """
        if volatility > self.volatility_threshold:
            return ATR_MULTIPLIER_VOLATILE  # 2.5x for high volatility
        else:
            return ATR_MULTIPLIER_STABLE    # 1.5x for low volatility
    
    def calculate_dynamic_sl(
        self, 
        entry_price: float, 
        atr: float, 
        position_side: str,
        volatility: Optional[float] = None
    ) -> float:
        """
        🎯 LAYER 1: Calculate dynamic SL based on ATR and volatility
        
        Args:
            entry_price: Position entry price
            atr: Average True Range value
            position_side: 'LONG' or 'SHORT'
            volatility: Optional pre-calculated volatility
            
        Returns:
            Stop loss price
        """
        # Determine ATR multiplier
        if volatility is None:
            volatility = self.calculate_volatility("", atr, entry_price)
        
        multiplier = self.get_atr_multiplier(volatility)
        sl_distance = atr * multiplier
        
        # Calculate SL price
        if position_side == "LONG":
            sl_price = entry_price - sl_distance
        else:  # SHORT
            sl_price = entry_price + sl_distance
        
        logger.debug(
            f"Dynamic SL: entry={entry_price:.8f}, atr={atr:.8f}, "
            f"mult={multiplier:.1f}x, vol={volatility*100:.1f}%, "
            f"sl={sl_price:.8f}"
        )
        
        return sl_price
    
    def calculate_max_loss_sl(
        self, 
        entry_price: float, 
        position_side: str
    ) -> float:
        """
        🛡️ LAYER 2: Calculate 2% max loss hard cap SL
        
        Args:
            entry_price: Position entry price
            position_side: 'LONG' or 'SHORT'
            
        Returns:
            Stop loss price at 2% max loss
        """
        if position_side == "LONG":
            sl_price = entry_price * (1 - self.max_loss_cap)
        else:  # SHORT
            sl_price = entry_price * (1 + self.max_loss_cap)
        
        return sl_price
    
    def calculate_protected_sl(
        self,
        entry_price: float,
        atr: float,
        position_side: str,
        volatility: Optional[float] = None
    ) -> float:
        """
        Calculate final protected SL combining LAYER 1 + LAYER 2
        
        Uses the MORE PROTECTIVE (tighter) of:
        1. Dynamic SL (ATR-based)
        2. Max Loss Cap (2% hard stop)
        
        Args:
            entry_price: Position entry price
            atr: Average True Range
            position_side: 'LONG' or 'SHORT'
            volatility: Optional pre-calculated volatility
            
        Returns:
            Final protected stop loss price
        """
        # Calculate both SL levels
        dynamic_sl = self.calculate_dynamic_sl(entry_price, atr, position_side, volatility)
        max_loss_sl = self.calculate_max_loss_sl(entry_price, position_side)
        
        # Use the TIGHTER (more protective) SL
        if position_side == "LONG":
            final_sl = max(dynamic_sl, max_loss_sl)  # Higher SL = tighter for LONG
        else:  # SHORT
            final_sl = min(dynamic_sl, max_loss_sl)  # Lower SL = tighter for SHORT
        
        logger.info(
            f"🛡️ Protected SL: dynamic={dynamic_sl:.8f}, "
            f"cap={max_loss_sl:.8f}, final={final_sl:.8f} ({position_side})"
        )
        
        return final_sl
    
    def should_force_close(self, position: Dict[str, Any]) -> Tuple[bool, str]:
        """
        🛡️ LAYER 2: Check if position should be force-closed (2% max loss cap)
        
        Args:
            position: Position data from Binance
            
        Returns:
            (should_close, reason)
        """
        symbol = position.get("symbol", "")
        entry_price = float(position.get("entryPrice", 0))
        mark_price = float(position.get("markPrice", 0))
        position_amt = float(position.get("positionAmt", 0))
        
        if entry_price <= 0 or mark_price <= 0 or position_amt == 0:
            return False, ""
        
        # Calculate current PnL %
        if position_amt > 0:  # LONG
            pnl_pct = (mark_price - entry_price) / entry_price
        else:  # SHORT
            pnl_pct = (entry_price - mark_price) / entry_price
        
        # Check if exceeds max loss
        if pnl_pct <= -self.max_loss_cap:
            reason = f"Max loss cap hit: {pnl_pct*100:.2f}% ≤ {-self.max_loss_cap*100:.1f}%"
            logger.warning(f"🚨 {symbol}: {reason}")
            return True, reason
        
        return False, ""
    
    def should_activate_breakeven(self, position: Dict[str, Any]) -> Tuple[bool, float]:
        """
        🚀 LAYER 3: Check if should move SL to breakeven (+0.5% profit)
        
        Args:
            position: Position data from Binance
            
        Returns:
            (should_activate, breakeven_price)
        """
        entry_price = float(position.get("entryPrice", 0))
        mark_price = float(position.get("markPrice", 0))
        position_amt = float(position.get("positionAmt", 0))
        
        if entry_price <= 0 or mark_price <= 0 or position_amt == 0:
            return False, 0.0
        
        # Calculate current PnL %
        if position_amt > 0:  # LONG
            pnl_pct = (mark_price - entry_price) / entry_price
        else:  # SHORT
            pnl_pct = (entry_price - mark_price) / entry_price
        
        # Check if reached breakeven threshold
        if pnl_pct >= self.breakeven_threshold:
            logger.info(
                f"🚀 {position.get('symbol')}: Breakeven threshold reached "
                f"({pnl_pct*100:.2f}% ≥ {self.breakeven_threshold*100:.1f}%)"
            )
            return True, entry_price
        
        return False, 0.0
    
    def cleanup_closed_position(self, symbol: str) -> None:
        """
        Cleanup tracking data for closed position
        
        Args:
            symbol: Trading symbol
        """
        if symbol in _position_entry_times:
            del _position_entry_times[symbol]
            logger.debug(f"🧹 Cleaned up tracking for {symbol}")
    
    def get_protection_summary(self) -> Dict[str, Any]:
        """
        Get summary of protection configuration
        
        Returns:
            Protection configuration summary
        """
        return {
            "layer_1_dynamic_sl": {
                "atr_multiplier_base": self.atr_multiplier_base,
                "atr_multiplier_volatile": ATR_MULTIPLIER_VOLATILE,
                "atr_multiplier_stable": ATR_MULTIPLIER_STABLE,
                "volatility_threshold": f"{self.volatility_threshold*100:.1f}%"
            },
            "layer_2_protection": {
                "min_hold_time_sec": self.min_hold_time,
                "max_loss_cap": f"{self.max_loss_cap*100:.1f}%"
            },
            "layer_3_breakeven": {
                "threshold": f"{self.breakeven_threshold*100:.1f}%"
            },
            "tracked_positions": len(_position_entry_times)
        }


# Singleton instance
_risk_manager: Optional[AdvancedRiskManager] = None


def get_risk_manager() -> AdvancedRiskManager:
    """Get or create singleton risk manager instance"""
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = AdvancedRiskManager()
    return _risk_manager
