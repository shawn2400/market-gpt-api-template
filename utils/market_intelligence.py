"""
Market Intelligence Engine - Self-Adaptive Trading System
==========================================================
Analyzes market conditions in real-time to enable dynamic strategy selection.

Components:
- Market Regime Detection (Trend/Sideways/Choppy)
- Volatility Classification (High/Medium/Low)
- Market Mood Analysis (Bullish/Bearish/Neutral)
- Trend Strength Scoring
- Liquidity Assessment

Author: AlgoGPT Team
Level: Hedge Fund Grade
"""

import logging
from typing import Dict, Literal, Optional, Tuple
from dataclasses import dataclass
import numpy as np

LOGGER = logging.getLogger("market_intelligence")

@dataclass
class MarketCondition:
    """Complete market analysis snapshot"""
    regime: Literal["trending", "sideways", "choppy", "volatile"]
    mood: Literal["bullish", "bearish", "neutral"]
    volatility: Literal["high", "medium", "low"]
    trend_strength: float  # 0-100
    confidence: float  # 0-100
    recommended_strategy: Literal["futures_long", "futures_short", "grid", "wait"]
    min_rr_threshold: float
    quality_threshold: float


class MarketIntelligence:
    """
    Advanced market analysis engine that adapts trading parameters
    based on real-time market conditions.
    """
    
    def __init__(self):
        self.logger = LOGGER
        
    def analyze_market(self, context: Dict) -> MarketCondition:
        """
        Comprehensive market analysis combining multiple indicators.
        
        Args:
            context: Market data from Context API (prices, indicators, etc)
            
        Returns:
            MarketCondition with regime, mood, volatility, and recommendations
        """
        regime = self._detect_regime(context)
        mood = self._classify_mood(context)
        volatility = self._classify_volatility(context)
        trend_strength = self._calculate_trend_strength(context)
        confidence = self._calculate_confidence(context, regime, mood)
        
        recommended_strategy = self._select_strategy(regime, mood, trend_strength)
        min_rr, quality = self._adaptive_thresholds(regime, mood, volatility)
        
        condition = MarketCondition(
            regime=regime,  # type: ignore
            mood=mood,  # type: ignore
            volatility=volatility,  # type: ignore
            trend_strength=trend_strength,
            confidence=confidence,
            recommended_strategy=recommended_strategy,  # type: ignore
            min_rr_threshold=min_rr,
            quality_threshold=quality
        )
        
        self.logger.info(
            f"Market Analysis: {regime.upper()} | {mood.upper()} | "
            f"Vol:{volatility} | Trend:{trend_strength:.1f} | "
            f"Strategy:{recommended_strategy} | MinRR:{min_rr:.2f}"
        )
        
        return condition
    
    def _detect_regime(self, ctx: Dict) -> str:
        """
        Detect market regime using ADX, Bollinger Bands, and price action.
        
        Logic:
        - Trending: Strong ADX (>25), clear direction
        - Sideways: Weak ADX (<20), price in range
        - Choppy: Moderate ADX (20-25), conflicting signals
        - Volatile: High ATR, rapid price swings
        """
        adx = ctx.get("adx", 20.0)
        atr_pct = ctx.get("atr_percent", 2.0)
        bb_width = ctx.get("bb_width_pct", 5.0)
        
        # High volatility regime
        if atr_pct > 5.0 or bb_width > 8.0:
            return "volatile"
        
        # Strong trend
        if adx > 25:
            return "trending"
        
        # Clear sideways/range
        if adx < 20 and bb_width < 4.0:
            return "sideways"
        
        # Mixed signals = choppy
        return "choppy"
    
    def _classify_mood(self, ctx: Dict) -> str:
        """
        Classify market mood using EMAs, MACD, and momentum.
        
        Logic:
        - Bullish: Price > EMAs, positive MACD, strong momentum
        - Bearish: Price < EMAs, negative MACD, weak momentum
        - Neutral: Mixed signals
        """
        price = ctx.get("close", 100.0)
        ema_20 = ctx.get("ema_20", price)
        ema_50 = ctx.get("ema_50", price)
        macd = ctx.get("macd", 0.0)
        rsi = ctx.get("rsi", 50.0)
        
        bullish_score = 0
        bearish_score = 0
        
        # EMA alignment
        if price > ema_20 > ema_50:
            bullish_score += 2
        elif price < ema_20 < ema_50:
            bearish_score += 2
        
        # MACD direction
        if macd > 0:
            bullish_score += 1
        elif macd < 0:
            bearish_score += 1
        
        # RSI momentum
        if rsi > 60:
            bullish_score += 1
        elif rsi < 40:
            bearish_score += 1
        
        if bullish_score > bearish_score + 1:
            return "bullish"
        elif bearish_score > bullish_score + 1:
            return "bearish"
        else:
            return "neutral"
    
    def _classify_volatility(self, ctx: Dict) -> str:
        """
        Classify volatility using ATR percentage.
        
        Logic:
        - High: ATR > 4% (aggressive markets)
        - Low: ATR < 2% (quiet markets)
        - Medium: 2-4% (normal conditions)
        """
        atr_pct = ctx.get("atr_percent", 2.5)
        
        if atr_pct > 4.0:
            return "high"
        elif atr_pct < 2.0:
            return "low"
        else:
            return "medium"
    
    def _calculate_trend_strength(self, ctx: Dict) -> float:
        """
        Calculate trend strength (0-100) using ADX and price momentum.
        
        Returns:
            0-100 score (0=no trend, 100=very strong trend)
        """
        adx = ctx.get("adx", 20.0)
        
        # ADX is primary trend strength indicator
        # ADX > 50 = very strong trend (rare)
        # ADX 25-50 = strong trend
        # ADX 20-25 = emerging trend
        # ADX < 20 = weak/no trend
        
        strength = min(100.0, adx * 2.0)  # Scale ADX to 0-100
        return strength
    
    def _calculate_confidence(self, ctx: Dict, regime: str, mood: str) -> float:
        """
        Calculate confidence in analysis (0-100).
        
        High confidence when:
        - Clear regime (trending or sideways)
        - Strong signals alignment
        - Good liquidity
        """
        confidence = 50.0  # Base
        
        # Regime clarity
        if regime == "trending":
            confidence += 20.0
        elif regime == "sideways":
            confidence += 15.0
        elif regime == "choppy":
            confidence -= 15.0
        
        # Mood clarity
        if mood in ["bullish", "bearish"]:
            confidence += 15.0
        else:
            confidence -= 10.0
        
        # ADX strength (higher ADX = more confidence)
        adx = ctx.get("adx", 20.0)
        if adx > 30:
            confidence += 15.0
        elif adx < 15:
            confidence -= 15.0
        
        return max(0.0, min(100.0, confidence))
    
    def _select_strategy(self, regime: str, mood: str, trend_strength: float) -> str:
        """
        Select optimal trading strategy based on market conditions.
        
        Strategy Selection Logic:
        - Strong Trend + Bullish → Futures Long
        - Strong Trend + Bearish → Futures Short
        - Sideways → GRID Trading
        - Choppy → Wait or GRID (conservative)
        - Volatile → Wait (too risky)
        """
        if regime == "volatile":
            return "wait"
        
        if regime == "trending" and trend_strength > 40:
            if mood == "bullish":
                return "futures_long"
            elif mood == "bearish":
                return "futures_short"
        
        if regime == "sideways":
            return "grid"
        
        if regime == "choppy":
            # In choppy markets, prefer GRID or wait
            if trend_strength < 30:
                return "grid"
            else:
                return "wait"
        
        # Default: wait for clearer conditions
        return "wait"
    
    def _adaptive_thresholds(
        self, 
        regime: str, 
        mood: str, 
        volatility: str
    ) -> Tuple[float, float]:
        """
        Calculate adaptive quality thresholds based on market conditions.
        
        Returns:
            (min_rr_threshold, quality_threshold)
            
        Threshold Logic:
        - Strong markets: Lower RR acceptable (easy to find setups)
        - Weak markets: Higher RR required (fewer opportunities)
        - High volatility: Higher RR (bigger stops needed)
        """
        base_rr = 1.3
        base_quality = 5.0
        
        # Regime adjustments
        if regime == "trending":
            base_rr -= 0.1  # Trends easier to trade
            base_quality -= 0.5
        elif regime == "choppy":
            base_rr += 0.3  # Need better setups
            base_quality += 1.0
        elif regime == "sideways":
            base_rr -= 0.2  # GRID trades have different RR logic
            base_quality -= 0.3
        
        # Mood adjustments
        if mood in ["bullish", "bearish"]:
            base_rr -= 0.05  # Clear direction helps
        else:
            base_rr += 0.1  # Neutral = uncertain
        
        # Volatility adjustments
        if volatility == "high":
            base_rr += 0.2  # Wider stops = need better RR
        elif volatility == "low":
            base_rr -= 0.05  # Tighter stops possible
        
        # Floor values for safety
        min_rr = max(1.2, base_rr)
        quality = max(4.0, base_quality)
        
        return (min_rr, quality)


# Global instance
_market_intelligence = None

def get_market_intelligence() -> MarketIntelligence:
    """Get singleton instance of MarketIntelligence"""
    global _market_intelligence
    if _market_intelligence is None:
        _market_intelligence = MarketIntelligence()
    return _market_intelligence
