# utils/market_adaptive_system.py
"""
Market Adaptive System - Auto-detect regime changes and adapt strategy
"""

from __future__ import annotations
import logging
from typing import Dict, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("algogpt.market_adaptive")


class MarketRegime(Enum):
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    BREAKOUT = "breakout"
    CHOPPY = "choppy"


@dataclass
class RegimeDetection:
    regime: MarketRegime
    confidence: float  # 0-1
    indicators: Dict[str, float]
    recommended_strategy: str
    recommended_combos: list[str]


class MarketAdaptiveSystem:
    """
    Market regime detection and strategy adaptation
    
    Features:
    - Auto-detect regime changes
    - Recommend optimal strategy per regime
    - Early warning for regime shifts
    """
    
    def __init__(self):
        self.current_regime: Optional[MarketRegime] = None
        self.regime_history: list[Tuple[float, MarketRegime]] = []
    
    def detect_regime(
        self,
        adx: float,
        atr_pct: float,
        bb_width: float,
        volume_ratio: float
    ) -> RegimeDetection:
        """Detect current market regime"""
        
        # TRENDING: Strong ADX, moderate ATR
        if adx > 25 and atr_pct < 0.05:
            return RegimeDetection(
                regime=MarketRegime.TRENDING,
                confidence=min(1.0, adx / 40),
                indicators={'adx': adx, 'atr_pct': atr_pct},
                recommended_strategy="trend_following",
                recommended_combos=["AI Trend + Momentum", "Quality Pullback"]
            )
        
        # VOLATILE: High ATR, high BB width
        if atr_pct > 0.05 or bb_width > 0.08:
            return RegimeDetection(
                regime=MarketRegime.VOLATILE,
                confidence=min(1.0, atr_pct / 0.10),
                indicators={'atr_pct': atr_pct, 'bb_width': bb_width},
                recommended_strategy="volatility_trading",
                recommended_combos=["Breakout + Volume"]
            )
        
        # BREAKOUT: High volume + expanding BB
        if volume_ratio > 1.5 and bb_width > 0.04:
            return RegimeDetection(
                regime=MarketRegime.BREAKOUT,
                confidence=min(1.0, volume_ratio / 2.0),
                indicators={'volume_ratio': volume_ratio, 'bb_width': bb_width},
                recommended_strategy="breakout",
                recommended_combos=["Breakout + Volume"]
            )
        
        # RANGING: Low ADX, tight BB
        if adx < 20 and bb_width < 0.04:
            return RegimeDetection(
                regime=MarketRegime.RANGING,
                confidence=min(1.0, (20 - adx) / 20),
                indicators={'adx': adx, 'bb_width': bb_width},
                recommended_strategy="mean_reversion",
                recommended_combos=["Ranging Market Bounds"]
            )
        
        # CHOPPY: Default
        return RegimeDetection(
            regime=MarketRegime.CHOPPY,
            confidence=0.5,
            indicators={'adx': adx},
            recommended_strategy="wait",
            recommended_combos=[]
        )
    
    def should_trade_in_regime(self, regime: MarketRegime) -> bool:
        """Check if trading is recommended in current regime"""
        return regime in [MarketRegime.TRENDING, MarketRegime.BREAKOUT, MarketRegime.RANGING]


__all__ = ["MarketAdaptiveSystem", "MarketRegime", "RegimeDetection"]
