#!/usr/bin/env python3
"""
Technical-Only Strategy Selector - Zero AI Dependencies
========================================================
Selects optimal trading strategy based PURELY on technical indicators:
- ADX (trend strength)
- Volatility (BB width)
- RSI (momentum)
- Volume
- EMA alignment

NO API calls, NO AI providers, runs 24/7 offline.
"""

import logging
from typing import Dict, Any, Literal
from dataclasses import dataclass

logger = logging.getLogger("algogpt.technical_strategy")

StrategyType = Literal["grid", "mean_reversion", "scalping", "wait"]

@dataclass
class TechnicalStrategy:
    """Technical-based strategy selection"""
    strategy: StrategyType
    confidence: float  # 0-100
    reasoning: str
    
class TechnicalStrategySelector:
    """Pure technical strategy selection - NO AI NEEDED"""
    
    def __init__(self):
        self.logger = logger
        self.logger.info("🔧 Technical Strategy Selector initialized (NO AI REQUIRED)")
    
    def select_strategy(self, indicators: Dict[str, Any], regime: str, mood: str) -> TechnicalStrategy:
        """
        Select strategy based PURELY on technical indicators.
        
        Args:
            indicators: Dict with ADX, RSI, Volatility, Volume, EMA
            regime: Market regime (TRENDING, CHOPPY, VOLATILE, etc)
            mood: Market mood (BULLISH, BEARISH, NEUTRAL)
            
        Returns:
            TechnicalStrategy with selection and confidence
        """
        # Extract indicators (with safe defaults)
        adx = float(indicators.get("adx", 20))  # Default: neutral trend
        rsi = float(indicators.get("rsi", 50))  # Default: neutral momentum
        volatility = float(indicators.get("volatility", 5))  # Default: low vol
        volume_sma_ratio = float(indicators.get("volume_sma_ratio", 1.0))  # Vol vs MA
        bb_width_pct = float(indicators.get("bb_width_pct", 5))  # Bollinger Bands width
        
        # ========== STRATEGY SELECTION LOGIC ==========
        
        # 1️⃣ TRENDING MARKETS (ADX > 25) → GRID or Scalping
        if adx > 25:
            # High trend + High volatility → GRID (capture big moves)
            if volatility > 7:
                return TechnicalStrategy(
                    strategy="grid",
                    confidence=75.0,
                    reasoning=f"GRID: Strong trend (ADX={adx:.1f}) + High volatility ({volatility:.1f}%) - capture big moves"
                )
            # High trend + Low volatility → Scalping (quick profits)
            else:
                return TechnicalStrategy(
                    strategy="scalping",
                    confidence=70.0,
                    reasoning=f"SCALPING: Strong trend (ADX={adx:.1f}) + Low volatility ({volatility:.1f}%) - quick gains"
                )
        
        # 2️⃣ CHOPPY/RANGING MARKETS (ADX < 20) → Mean-Reversion
        if adx < 20:
            # Narrow range + High RSI/Low RSI extremes → Mean-Reversion (bounce trades)
            if bb_width_pct < 4:  # Narrow bands = tight range
                if rsi > 70 or rsi < 30:  # Oversold/overbought
                    return TechnicalStrategy(
                        strategy="mean_reversion",
                        confidence=72.0,
                        reasoning=f"MEAN-REVERSION: Tight range (BB={bb_width_pct:.1f}%) + RSI extreme ({rsi:.0f}) - bounce setup"
                    )
            
            # Choppy with normal range → Grid (scalp the chop)
            return TechnicalStrategy(
                strategy="grid",
                confidence=60.0,
                reasoning=f"GRID: Choppy market (ADX={adx:.1f}) - scalp the ranges"
            )
        
        # 3️⃣ VOLATILE MARKETS (volatility > 10) + WEAK TREND → WAIT
        if volatility > 10 and adx < 25:
            return TechnicalStrategy(
                strategy="wait",
                confidence=40.0,
                reasoning=f"WAIT: High volatility ({volatility:.1f}%) + weak trend (ADX={adx:.1f}) - too risky"
            )
        
        # 4️⃣ DEFAULT: Moderate conditions → Grid
        return TechnicalStrategy(
            strategy="grid",
            confidence=55.0,
            reasoning=f"GRID (default): ADX={adx:.1f}, Vol={volatility:.1f}%, RSI={rsi:.0f}"
        )


# ============ SINGLETON INSTANCE ============
_selector = None

def get_technical_strategy_selector() -> TechnicalStrategySelector:
    """Get or create singleton instance"""
    global _selector
    if _selector is None:
        _selector = TechnicalStrategySelector()
    return _selector
