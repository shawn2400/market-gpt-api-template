#!/usr/bin/env python3
"""
Entry Timing Optimizer - Precision Entry Timing
===============================================
Prevents quick in/out trades with losses by analyzing EXACT timing
for entry. Waits for optimal moment instead of entering immediately.

Prevents scenarios like:
- XRPUSDT: Entry @ 18:16:12 → Exit @ 18:17:35 (83 sec) = -$0.59

Analyzes:
- Price action micro-structure
- Volume confirmation
- Order flow direction
- Momentum acceleration
- Support/Resistance proximity

Only approves entry at OPTIMAL timing.
Part of MetaBrain v9.1 - Precision Entry System
"""

import logging
import time
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger("algogpt.entry_timing")


@dataclass
class EntryTiming:
    """Entry timing analysis result"""
    ready: bool  # True if timing is good NOW
    confidence: float  # 0-100
    wait_seconds: Optional[int]  # Suggested wait time if not ready
    reasoning: str  # Why ready/not ready
    price_target: Optional[float]  # Optimal entry price
    

class EntryTimingOptimizer:
    """
    Optimizes entry timing to prevent premature entries.
    
    Philosophy:
    - Better to wait 30 seconds for good entry than rush in
    - Confirm momentum before entry
    - Wait for volume confirmation
    - Avoid entering right at resistance/support
    """
    
    def __init__(self):
        self.logger = logger
        
        # Timing thresholds
        self.MIN_VOLUME_RATIO = 1.1  # Need 110% of avg volume
        self.MIN_MOMENTUM_DURATION = 15  # Momentum must last 15+ seconds
        self.MIN_DISTANCE_FROM_LEVEL = 0.3  # 0.3% from S/R
    
    def check_entry_timing(
        self,
        symbol: str,
        side: str,  # LONG/SHORT
        entry_price: float,
        market_ctx: Dict[str, Any],
        recent_candles: Optional[list] = None
    ) -> EntryTiming:
        """
        Check if NOW is good timing for entry.
        
        Args:
            symbol: Trading symbol
            side: LONG or SHORT
            entry_price: Proposed entry price
            market_ctx: Current market data
            recent_candles: Last 5-10 candles for micro-analysis
        
        Returns:
            EntryTiming with decision
        """
        self.logger.info(f"⏱️ Entry Timing Check: {symbol} {side} @ {entry_price}")
        
        ready = True
        confidence = 80.0
        wait_seconds = None
        reasons = []
        
        # Check 1: Volume confirmation
        vol_ok, vol_reason = self._check_volume_confirmation(market_ctx)
        if not vol_ok:
            ready = False
            confidence -= 20
            wait_seconds = 30
            reasons.append(vol_reason)
        else:
            reasons.append(vol_reason)
        
        # Check 2: Momentum confirmation
        mom_ok, mom_reason = self._check_momentum_confirmation(
            side, market_ctx, recent_candles
        )
        if not mom_ok:
            ready = False
            confidence -= 15
            if not wait_seconds:
                wait_seconds = 20
            reasons.append(mom_reason)
        else:
            reasons.append(mom_reason)
        
        # Check 3: Distance from key levels
        level_ok, level_reason, optimal_price = self._check_distance_from_levels(
            side, entry_price, market_ctx
        )
        if not level_ok:
            ready = False
            confidence -= 10
            if not wait_seconds:
                wait_seconds = 15
            reasons.append(level_reason)
        else:
            reasons.append(level_reason)
        
        # Check 4: Recent price action (avoid whipsaws)
        whipsaw_ok, whipsaw_reason = self._check_whipsaw_risk(
            recent_candles
        )
        if not whipsaw_ok:
            ready = False
            confidence -= 15
            if not wait_seconds:
                wait_seconds = 25
            reasons.append(whipsaw_reason)
        else:
            reasons.append(whipsaw_reason)
        
        # Generate reasoning
        if ready:
            reasoning = f"✅ Timing optimal: {'; '.join(reasons)}"
        else:
            reasoning = f"⏳ Wait {wait_seconds}s: {'; '.join(reasons)}"
        
        result = EntryTiming(
            ready=ready,
            confidence=max(0, confidence),
            wait_seconds=wait_seconds if not ready else None,
            reasoning=reasoning,
            price_target=optimal_price
        )
        
        status = "✅ READY" if ready else f"⏳ WAIT {wait_seconds}s"
        self.logger.info(f"{status} | Confidence={confidence:.0f}% | {reasoning[:100]}")
        
        return result
    
    def _check_volume_confirmation(
        self,
        market_ctx: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """Check if volume confirms the move"""
        
        volume = market_ctx.get("volume", 0)
        vol_sma = market_ctx.get("volume_sma_20", volume)
        
        if vol_sma and vol_sma > 0:
            vol_ratio = volume / vol_sma
            
            if vol_ratio >= self.MIN_VOLUME_RATIO:
                return (True, f"Volume confirmed ({vol_ratio:.1f}x avg)")
            else:
                return (False, f"Volume weak ({vol_ratio:.1f}x avg, need {self.MIN_VOLUME_RATIO}x)")
        
        return (False, "No volume data available")
    
    def _check_momentum_confirmation(
        self,
        side: str,
        market_ctx: Dict[str, Any],
        recent_candles: Optional[list]
    ) -> Tuple[bool, str]:
        """Check if momentum confirms direction"""
        
        # MACD check
        macd = market_ctx.get("macd", 0)
        macd_signal = market_ctx.get("macd_signal", 0)
        
        if side == "LONG":
            if macd > macd_signal and macd > 0:
                return (True, "Momentum bullish (MACD +)")
            else:
                return (False, "Momentum not confirmed for LONG")
        else:  # SHORT
            if macd < macd_signal and macd < 0:
                return (True, "Momentum bearish (MACD -)")
            else:
                return (False, "Momentum not confirmed for SHORT")
    
    def _check_distance_from_levels(
        self,
        side: str,
        entry_price: float,
        market_ctx: Dict[str, Any]
    ) -> Tuple[bool, str, Optional[float]]:
        """Check distance from support/resistance"""
        
        high_24h = market_ctx.get("high_24h", entry_price)
        low_24h = market_ctx.get("low_24h", entry_price)
        
        optimal_price = None
        
        if side == "LONG":
            # For LONG, we want to be ABOVE support
            dist_from_support = ((entry_price - low_24h) / low_24h * 100) if low_24h > 0 else 0
            
            if dist_from_support >= self.MIN_DISTANCE_FROM_LEVEL:
                return (True, f"Safe distance from support ({dist_from_support:.2f}%)", None)
            else:
                # Suggest waiting for bounce
                optimal_price = low_24h * (1 + self.MIN_DISTANCE_FROM_LEVEL / 100)
                return (
                    False,
                    f"Too close to support ({dist_from_support:.2f}%), wait for bounce to {optimal_price:.6f}",
                    optimal_price
                )
        
        else:  # SHORT
            # For SHORT, we want to be BELOW resistance
            dist_from_resistance = ((high_24h - entry_price) / high_24h * 100) if high_24h > 0 else 0
            
            if dist_from_resistance >= self.MIN_DISTANCE_FROM_LEVEL:
                return (True, f"Safe distance from resistance ({dist_from_resistance:.2f}%)", None)
            else:
                # Suggest waiting for rejection
                optimal_price = high_24h * (1 - self.MIN_DISTANCE_FROM_LEVEL / 100)
                return (
                    False,
                    f"Too close to resistance ({dist_from_resistance:.2f}%), wait for rejection to {optimal_price:.6f}",
                    optimal_price
                )
    
    def _check_whipsaw_risk(
        self,
        recent_candles: Optional[list]
    ) -> Tuple[bool, str]:
        """Check for whipsaw/choppy price action"""
        
        if not recent_candles or len(recent_candles) < 3:
            return (True, "No recent candle data")
        
        # Count direction changes in last 3-5 candles
        directions = []
        for i in range(min(5, len(recent_candles))):
            candle = recent_candles[i]
            if isinstance(candle, dict):
                open_price = candle.get("open", 0)
                close_price = candle.get("close", 0)
                
                if close_price > open_price:
                    directions.append("UP")
                elif close_price < open_price:
                    directions.append("DOWN")
        
        # Count direction changes
        changes = 0
        for i in range(len(directions) - 1):
            if directions[i] != directions[i+1]:
                changes += 1
        
        # If too many changes (>2 in 5 candles), it's choppy
        if changes > 2:
            return (False, f"Choppy price action ({changes} direction changes)")
        
        return (True, "Price action stable")


# Singleton instance
_entry_timing: Optional[EntryTimingOptimizer] = None


def get_entry_timing_optimizer() -> EntryTimingOptimizer:
    """Get or create singleton entry timing optimizer"""
    global _entry_timing
    if _entry_timing is None:
        _entry_timing = EntryTimingOptimizer()
    return _entry_timing


def check_entry_timing(
    symbol: str,
    side: str,
    entry_price: float,
    market_ctx: Dict[str, Any],
    recent_candles: Optional[list] = None
) -> EntryTiming:
    """
    Convenience function for entry timing check.
    
    Returns timing decision with reasoning.
    """
    optimizer = get_entry_timing_optimizer()
    return optimizer.check_entry_timing(
        symbol, side, entry_price, market_ctx, recent_candles
    )
