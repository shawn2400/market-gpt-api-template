# -*- coding: utf-8 -*-
# utils/strategy_selector.py
"""
Auto-Strategy Selection Engine
Chooses optimal strategy based on support/resistance proximity and market conditions
"""
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("algogpt.strategy_selector")


class StrategySelector:
    """
    Automatically selects trading strategy based on:
    - Price proximity to support/resistance levels
    - Market regime (TRENDING, CHOPPY, VOLATILE, SIDEWAYS)
    - Technical indicators (ADX, RSI, volatility)
    """
    
    def __init__(self):
        self.logger = logger
    
    def select_strategy(
        self,
        symbol: str,
        current_price: float,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Auto-select optimal trading strategy.
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
            context: Market context with indicators and levels
            
        Returns:
            Dict with strategy, entry_price, reasoning
        """
        # Get support/resistance levels
        support, resistance = self._get_support_resistance(symbol, current_price, context)
        
        # Calculate distances
        distance_to_support = abs(current_price - support) / current_price if support else 1.0
        distance_to_resistance = abs(current_price - resistance) / current_price if resistance else 1.0
        
        # Get market regime
        regime = context.get("regime", "CHOPPY")
        adx = context.get("adx", 20.0)
        rsi = context.get("rsi", 50.0)
        atr_pct = context.get("atr_percent", 2.0)
        
        # Strategy selection logic (like DynamicTradingAgent.auto_select_strategy)
        strategy = self._determine_strategy(
            distance_to_support,
            distance_to_resistance,
            regime,
            adx,
            rsi,
            atr_pct
        )
        
        # Calculate entry price
        entry_price = self._calculate_entry_price(
            current_price,
            strategy,
            support,
            resistance
        )
        
        # Build reasoning
        reasoning = self._build_reasoning(
            strategy,
            distance_to_support,
            distance_to_resistance,
            regime,
            support,
            resistance
        )
        
        return {
            "strategy": strategy,
            "entry_price": entry_price,
            "support_level": support,
            "resistance_level": resistance,
            "distance_to_support": distance_to_support,
            "distance_to_resistance": distance_to_resistance,
            "reasoning": reasoning
        }
    
    def _get_support_resistance(
        self,
        symbol: str,
        current_price: float,
        context: Dict[str, Any]
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Get support and resistance levels.
        Uses technical levels from context or calculates from price action.
        """
        # Try to get from context first
        support = context.get("support_level")
        resistance = context.get("resistance_level")
        
        if support and resistance:
            return support, resistance
        
        # Calculate from Bollinger Bands if available
        bb_lower = context.get("bb_lower")
        bb_upper = context.get("bb_upper")
        
        if bb_lower and bb_upper:
            return bb_lower, bb_upper
        
        # Fallback: use EMA levels as dynamic support/resistance
        ema_20 = context.get("ema_20") or context.get("ema21")
        ema_50 = context.get("ema_50") or context.get("ema50")
        
        if ema_20 and ema_50:
            # Lower EMA = support, higher EMA = resistance
            support = min(ema_20, ema_50)
            resistance = max(ema_20, ema_50)
            return support, resistance
        
        # Last resort: use ATR-based levels
        atr = context.get("atr") or context.get("atr14")
        if atr:
            support = current_price - (atr * 2)
            resistance = current_price + (atr * 2)
            return support, resistance
        
        # No levels available - use price ±3%
        return current_price * 0.97, current_price * 1.03
    
    def _determine_strategy(
        self,
        dist_support: float,
        dist_resistance: float,
        regime: str,
        adx: float,
        rsi: float,
        atr_pct: float
    ) -> str:
        """
        Determine optimal strategy based on support/resistance proximity.
        
        Simple logic (like DynamicTradingAgent):
        - Closer to support → "dip" (buy the dip)
        - Closer to resistance → "breakout" (breakout trade)
        """
        # Simple proximity-based selection
        if dist_support < dist_resistance:
            # Closer to support → buy the dip
            return "dip"
        else:
            # Closer to resistance → breakout
            return "breakout"
    
    def _calculate_entry_price(
        self,
        current_price: float,
        strategy: str,
        support: Optional[float],
        resistance: Optional[float]
    ) -> float:
        """
        Calculate optimal entry price based on strategy.
        
        Like DynamicTradingAgent.calculate_entry_price():
        - dip: support * 1.01 (1% above support to avoid false breaks)
        - breakout: resistance * 1.005 (0.5% above resistance for confirmation)
        - Others: current price with small offset
        """
        if strategy == "dip" and support:
            # Buy 1% above support to avoid false breaks
            return support * 1.01
        
        elif strategy == "breakout" and resistance:
            # Buy 0.5% above resistance for confirmation
            return resistance * 1.005
        
        elif strategy == "mean_reversion":
            # Enter at current price (or slightly better)
            return current_price * 0.999  # 0.1% better fill
        
        elif strategy == "grid":
            # Grid uses range midpoint, but for single entry use current price
            return current_price
        
        elif strategy == "trend_following":
            # Enter on small pullback
            return current_price * 0.997  # 0.3% pullback
        
        else:
            # Default: current price
            return current_price
    
    def _build_reasoning(
        self,
        strategy: str,
        dist_support: float,
        dist_resistance: float,
        regime: str,
        support: Optional[float],
        resistance: Optional[float]
    ) -> str:
        """Build human-readable reasoning for strategy selection"""
        if strategy == "dip":
            return (
                f"Dip buying near support (distance: {dist_support*100:.1f}% vs "
                f"{dist_resistance*100:.1f}% to resistance) in {regime} market"
            )
        elif strategy == "breakout":
            return (
                f"Breakout near resistance (distance: {dist_resistance*100:.1f}% vs "
                f"{dist_support*100:.1f}% to support) with strong momentum"
            )
        elif strategy == "mean_reversion":
            return f"Mean reversion in {regime} market (support: {support}, resistance: {resistance})"
        elif strategy == "grid":
            return f"GRID strategy optimal for {regime} market with low volatility"
        elif strategy == "trend_following":
            return f"Trend following in {regime} market"
        else:
            return f"Auto-selected {strategy} for {regime} market"


# Singleton instance
_strategy_selector: Optional[StrategySelector] = None

def get_strategy_selector() -> StrategySelector:
    """Get singleton StrategySelector instance"""
    global _strategy_selector
    if _strategy_selector is None:
        _strategy_selector = StrategySelector()
    return _strategy_selector
