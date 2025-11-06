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
- Multi-Timeframe Analysis (15M/1H/4H)

Author: AlgoGPT Team
Level: Hedge Fund Grade
"""

import logging
from typing import Dict, Literal, Optional, Tuple, List
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
    tf_alignment: Optional[str] = None  # Multi-TF trend alignment
    recommended_intervals: Optional[List[str]] = None  # Which TFs to fetch


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
        
        # Auto-save market state to database
        try:
            from utils.data_persistence import get_persistence
            persistence = get_persistence()
            
            symbol = context.get("symbol", "UNKNOWN")
            
            persistence.save_market_state(
                symbol=symbol,
                regime=regime,
                mood=mood,
                volatility=volatility,
                trend_strength=trend_strength,
                strategy=recommended_strategy,
                min_rr=min_rr,
                min_quality=quality,
                indicators={
                    "adx": context.get("adx"),
                    "atr_pct": context.get("atr_percent"),
                    "macd": context.get("macd"),
                    "rsi": context.get("rsi"),
                    "ema_20": context.get("ema_20"),
                    "ema_50": context.get("ema_50")
                }
            )
        except Exception as e:
            self.logger.warning(f"Failed to save market state to DB: {e}")
        
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
        adx = ctx.get("adx")
        if adx is None:
            adx = 20.0
        atr_pct = ctx.get("atr_percent")
        if atr_pct is None:
            atr_pct = 2.0
        bb_width = ctx.get("bb_width_pct")
        if bb_width is None:
            bb_width = 5.0
        
        # High volatility regime
        if atr_pct > 5.0 or bb_width > 8.0:
            return "volatile"
        
        # Strong trend
        if adx > 25:
            return "trending"
        
        # Clear sideways/range
        if adx < 20 and bb_width is not None and bb_width < 4.0:
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
        price = ctx.get("close")
        if price is None:
            price = 100.0
        ema_20 = ctx.get("ema_20")
        if ema_20 is None:
            ema_20 = price
        ema_50 = ctx.get("ema_50")
        if ema_50 is None:
            ema_50 = price
        macd = ctx.get("macd")
        if macd is None:
            macd = 0.0
        rsi = ctx.get("rsi")
        if rsi is None:
            rsi = 50.0
        
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
        atr_pct = ctx.get("atr_percent")
        if atr_pct is None:
            atr_pct = 2.5
        
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
        adx = ctx.get("adx")
        if adx is None:
            adx = 20.0
        
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
        adx = ctx.get("adx")
        if adx is None:
            adx = 20.0
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
            # In choppy markets, ALWAYS prefer GRID trading!
            # CHOPPY = Range-bound = Perfect for GRID
            # Only wait if trend is very strong (about to break out)
            if trend_strength < 60:  # Most choppy cases
                return "grid"
            else:
                return "wait"  # Very rare: choppy with strong trend = wait for breakout
        
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
            
        Threshold Logic - FULLY ADAPTIVE FOR ALL MARKET CONDITIONS:
        - CHOPPY/SIDEWAYS: Very low RR (1.1-1.15) - scalping & range trading
        - TRENDING: Moderate RR (1.2-1.3) - breakout trades
        - VOLATILE: Higher RR (1.4+) - wider stops needed
        
        🎯 GOAL: Generate trades in ALL market conditions (big, small, intermediate)
        """
        # 🚀 NEW ADAPTIVE BASE - Much lower for more opportunities
        if regime == "choppy":
            # CHOPPY = Perfect for scalping & small range trades
            base_rr = 1.1  # ✅ LOWERED from 1.3 to 1.1
            base_quality = 4.0  # Accept more setups
        elif regime == "sideways":
            # SIDEWAYS = GRID trading + range bounces
            base_rr = 1.15  # ✅ LOWERED from 1.3 to 1.15
            base_quality = 4.2
        elif regime == "trending":
            # TRENDING = Traditional breakout trades
            base_rr = 1.25  # ✅ LOWERED from 1.3 to 1.25
            base_quality = 4.5
        elif regime == "volatile":
            # VOLATILE = Need higher RR due to wider stops
            base_rr = 1.4
            base_quality = 5.0
        else:
            # Fallback
            base_rr = 1.2
            base_quality = 4.5
        
        # Mood adjustments - MINIMAL impact for CHOPPY markets
        # CHOPPY/SIDEWAYS don't need mood penalty (they're meant for neutral markets!)
        if regime not in ["choppy", "sideways"]:
            if mood in ["bullish", "bearish"]:
                base_rr -= 0.05  # Clear direction helps
            else:
                base_rr += 0.05  # Neutral adds slight caution
        # else: CHOPPY/SIDEWAYS → no mood penalty (neutral is GOOD for these strategies!)
        
        # Volatility adjustments
        if volatility == "high":
            base_rr += 0.15  # ✅ Reduced from 0.2
        elif volatility == "low":
            base_rr -= 0.05  # Tighter stops possible
        
        # 🚨 CRITICAL: Lower floor values to allow more trades
        min_rr = max(1.05, base_rr)  # ✅ LOWERED from 1.2 to 1.05
        quality = max(3.5, base_quality)  # ✅ LOWERED from 4.0 to 3.5
        
        return (min_rr, quality)
    
    def analyze_multi_tf(self, multi_tf_contexts: Dict[str, Dict]) -> MarketCondition:
        """
        Multi-timeframe analysis combining 15M, 1H, and 4H data.
        
        Strategy:
        - 4H: Overall trend direction (primary bias)
        - 1H: Intermediate trend confirmation
        - 15M: Entry timing and execution
        
        Args:
            multi_tf_contexts: Dict mapping interval -> context data
            Example: {"15m": {...}, "1h": {...}, "4h": {...}}
            
        Returns:
            Enhanced MarketCondition with TF alignment info
        """
        # Fallback to single-TF if multi-TF data not available
        if "15m" not in multi_tf_contexts:
            self.logger.warning("No 15m data in multi-TF analysis, using first available")
            first_key = list(multi_tf_contexts.keys())[0] if multi_tf_contexts else "15m"
            return self.analyze_market(multi_tf_contexts.get(first_key, {}))
        
        # Analyze each timeframe
        tf_15m = multi_tf_contexts.get("15m", {})
        tf_1h = multi_tf_contexts.get("1h", tf_15m)
        tf_4h = multi_tf_contexts.get("4h", tf_15m)
        
        # Get individual analyses
        regime_15m = self._detect_regime(tf_15m)
        regime_1h = self._detect_regime(tf_1h)
        regime_4h = self._detect_regime(tf_4h)
        
        mood_15m = self._classify_mood(tf_15m)
        mood_1h = self._classify_mood(tf_1h)
        mood_4h = self._classify_mood(tf_4h)
        
        # Multi-TF trend alignment (most powerful signal)
        tf_alignment = self._check_tf_alignment(mood_15m, mood_1h, mood_4h)
        
        # Use weighted combination for final decision
        # 4H carries most weight for trend, 15M for execution
        final_regime = regime_4h if regime_4h in ["trending", "volatile"] else regime_15m
        final_mood = mood_4h if tf_alignment in ["strong_bull", "strong_bear"] else mood_15m
        
        volatility = self._classify_volatility(tf_15m)
        trend_strength = self._calculate_trend_strength(tf_4h)  # Use 4H for strength
        
        # Boost confidence when all TFs align
        base_confidence = self._calculate_confidence(tf_15m, final_regime, final_mood)
        if tf_alignment in ["strong_bull", "strong_bear"]:
            confidence = min(100.0, base_confidence + 20.0)  # +20% for alignment
        elif tf_alignment in ["weak_bull", "weak_bear"]:
            confidence = min(100.0, base_confidence + 10.0)
        else:
            confidence = base_confidence
        
        recommended_strategy = self._select_strategy(final_regime, final_mood, trend_strength)
        min_rr, quality = self._adaptive_thresholds(final_regime, final_mood, volatility)
        
        # Determine which intervals to fetch next time (dynamic)
        recommended_intervals = self._recommend_intervals(final_regime, volatility)
        
        condition = MarketCondition(
            regime=final_regime,  # type: ignore
            mood=final_mood,  # type: ignore
            volatility=volatility,  # type: ignore
            trend_strength=trend_strength,
            confidence=confidence,
            recommended_strategy=recommended_strategy,  # type: ignore
            min_rr_threshold=min_rr,
            quality_threshold=quality,
            tf_alignment=tf_alignment,
            recommended_intervals=recommended_intervals
        )
        
        self.logger.info(
            f"Multi-TF Analysis: {final_regime.upper()} | {final_mood.upper()} | "
            f"Vol:{volatility} | TF-Align:{tf_alignment} | "
            f"Strategy:{recommended_strategy} | MinRR:{min_rr:.2f} | Confidence:{confidence:.1f}%"
        )
        
        return condition
    
    def _check_tf_alignment(self, mood_15m: str, mood_1h: str, mood_4h: str) -> str:
        """
        Check multi-timeframe trend alignment.
        
        Returns:
            - strong_bull: All TFs bullish
            - strong_bear: All TFs bearish
            - weak_bull: 1H+4H bullish, 15M mixed/bearish
            - weak_bear: 1H+4H bearish, 15M mixed/bullish
            - mixed: No clear alignment
        """
        # All aligned bullish
        if mood_15m == "bullish" and mood_1h == "bullish" and mood_4h == "bullish":
            return "strong_bull"
        
        # All aligned bearish
        if mood_15m == "bearish" and mood_1h == "bearish" and mood_4h == "bearish":
            return "strong_bear"
        
        # Higher TFs bullish (1H + 4H)
        if mood_1h == "bullish" and mood_4h == "bullish":
            return "weak_bull"
        
        # Higher TFs bearish (1H + 4H)
        if mood_1h == "bearish" and mood_4h == "bearish":
            return "weak_bear"
        
        # No clear alignment
        return "mixed"
    
    def _recommend_intervals(self, regime: str, volatility: str) -> List[str]:
        """
        Dynamically recommend which timeframes to fetch based on conditions.
        
        Strategy:
        - Trending markets: Need higher TFs for trend confirmation
        - Choppy/Sideways: 15M sufficient (GRID trading)
        - Volatile: All TFs to assess risk
        """
        # Always include 15M (execution timeframe)
        intervals = ["15m"]
        
        # Add higher TFs based on regime
        if regime in ["trending", "volatile"]:
            # Need multi-TF confirmation for trends
            intervals.extend(["1h", "4h"])
        elif volatility == "high":
            # High volatility = check higher TFs for stability
            intervals.append("1h")
        
        return intervals


# Global instance
_market_intelligence = None

def get_market_intelligence() -> MarketIntelligence:
    """Get singleton instance of MarketIntelligence"""
    global _market_intelligence
    if _market_intelligence is None:
        _market_intelligence = MarketIntelligence()
    return _market_intelligence
