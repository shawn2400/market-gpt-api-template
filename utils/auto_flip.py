# utils/auto_flip.py
"""
Auto-Flip Multi-Timeframe Weighted Analysis
============================================
Provides weighted multi-timeframe analysis for position flipping decisions.

**Timeframe Priority (Sniper-Grade):**
- 4H = 50% weight (Primary trend direction)
- 1H = 30% weight (Confirmation)
- 15M = 20% weight (Entry timing only)

Author: AlgoGPT Team
Level: Hedge Fund Grade
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger("auto_flip")


@dataclass
class WeightedTFAnalysis:
    """Result of weighted multi-timeframe analysis"""
    dominant_timeframe: str  # Which TF is driving the decision
    weighted_confidence: float  # 0-100
    tf_scores: Dict[str, float]  # Individual TF confidence scores
    trend_direction: str  # LONG, SHORT, NEUTRAL
    alignment_status: str  # STRONG, MODERATE, WEAK, CONFLICTING
    should_flip: bool
    reason: str


class MultiTFWeightedAnalyzer:
    """
    Analyzes multiple timeframes with priority weighting.
    
    **Decision Logic:**
    1. 4H determines overall trend direction (50% weight)
    2. 1H confirms or rejects the 4H trend (30% weight)
    3. 15M only used for entry timing (20% weight)
    
    **Flip Criteria:**
    - STRONG alignment (all TFs agree) = High confidence flip
    - MODERATE alignment (4H + 1H agree, 15M differs) = Medium confidence
    - WEAK alignment (only 4H strong) = Low confidence, wait
    - CONFLICTING (4H vs 1H disagree) = NO FLIP
    """
    
    # Timeframe weights (must sum to 1.0)
    TF_WEIGHTS = {
        "4h": 0.50,  # Primary trend direction
        "1h": 0.30,  # Confirmation
        "15m": 0.20,  # Entry timing
    }
    
    def __init__(self):
        self.logger = logger
    
    def analyze_multi_tf_weighted(
        self,
        tf_contexts: Dict[str, Dict[str, Any]],
        current_side: Optional[str] = None
    ) -> WeightedTFAnalysis:
        """
        Perform weighted multi-timeframe analysis.
        
        Args:
            tf_contexts: Dict mapping interval -> context data
                Example: {"4h": {...}, "1h": {...}, "15m": {...}}
            current_side: Current position side (LONG/SHORT) if any
            
        Returns:
            WeightedTFAnalysis with decision and confidence
        """
        # Validate we have all required timeframes
        required_tfs = ["4h", "1h", "15m"]
        missing_tfs = [tf for tf in required_tfs if tf not in tf_contexts]
        
        if missing_tfs:
            self.logger.warning(f"Missing timeframes: {missing_tfs}, using available data")
        
        # Analyze each timeframe
        tf_scores = {}
        tf_trends = {}
        
        for interval in required_tfs:
            if interval not in tf_contexts:
                continue
            
            ctx = tf_contexts[interval]
            trend, confidence = self._analyze_single_tf(ctx, interval)
            
            tf_scores[interval] = confidence
            tf_trends[interval] = trend
            
            self.logger.info(
                f"📊 TF Analysis [{interval.upper()}]: Trend={trend}, "
                f"Confidence={confidence:.1f}%, Weight={self.TF_WEIGHTS.get(interval, 0)*100:.0f}%"
            )
        
        # Calculate weighted confidence and determine dominant trend
        weighted_conf, dominant_trend = self._calculate_weighted_decision(
            tf_scores, tf_trends
        )
        
        # Determine dominant timeframe (highest weighted contribution)
        dominant_tf = self._get_dominant_timeframe(tf_scores)
        
        # Check alignment between timeframes
        alignment = self._check_tf_alignment(tf_trends)
        
        # Decide if we should flip
        should_flip, reason = self._should_flip_decision(
            alignment, weighted_conf, dominant_trend, current_side
        )
        
        result = WeightedTFAnalysis(
            dominant_timeframe=dominant_tf,
            weighted_confidence=weighted_conf,
            tf_scores=tf_scores,
            trend_direction=dominant_trend,
            alignment_status=alignment,
            should_flip=should_flip,
            reason=reason
        )
        
        self.logger.info(
            f"🎯 Multi-TF Decision: {dominant_trend} | Confidence={weighted_conf:.1f}% | "
            f"Alignment={alignment} | Flip={should_flip} | Reason={reason}"
        )
        
        return result
    
    def _analyze_single_tf(
        self,
        ctx: Dict[str, Any],
        interval: str
    ) -> Tuple[str, float]:
        """
        Analyze single timeframe context.
        
        Returns:
            (trend_direction, confidence_score)
            trend_direction: LONG, SHORT, NEUTRAL
            confidence_score: 0-100
        """
        # Extract indicators
        adx = ctx.get("adx", 20.0)
        if adx is None:
            adx = 20.0
        
        rsi = ctx.get("rsi", 50.0)
        if rsi is None:
            rsi = 50.0
        
        macd = ctx.get("macd", 0.0)
        if macd is None:
            macd = 0.0
        
        price = ctx.get("close", 0.0)
        ema_20 = ctx.get("ema_20", price)
        ema_50 = ctx.get("ema_50", price)
        
        if ema_20 is None:
            ema_20 = price
        if ema_50 is None:
            ema_50 = price
        
        # Score bullish/bearish signals
        bullish_score = 0.0
        bearish_score = 0.0
        
        # EMA alignment (strongest signal)
        if price > ema_20 > ema_50:
            bullish_score += 30.0
        elif price < ema_20 < ema_50:
            bearish_score += 30.0
        
        # MACD direction
        if macd > 0:
            bullish_score += 20.0
        elif macd < 0:
            bearish_score += 20.0
        
        # RSI momentum
        if rsi > 60:
            bullish_score += 15.0
        elif rsi > 50:
            bullish_score += 5.0
        elif rsi < 40:
            bearish_score += 15.0
        elif rsi < 50:
            bearish_score += 5.0
        
        # ADX trend strength (boosts confidence)
        if adx > 25:
            strength_boost = min(35.0, (adx - 25) * 1.5)
            if bullish_score > bearish_score:
                bullish_score += strength_boost
            else:
                bearish_score += strength_boost
        
        # Determine trend and confidence
        if bullish_score > bearish_score + 10:
            trend = "LONG"
            confidence = min(100.0, bullish_score)
        elif bearish_score > bullish_score + 10:
            trend = "SHORT"
            confidence = min(100.0, bearish_score)
        else:
            trend = "NEUTRAL"
            confidence = 100.0 - abs(bullish_score - bearish_score)
        
        return (trend, confidence)
    
    def _calculate_weighted_decision(
        self,
        tf_scores: Dict[str, float],
        tf_trends: Dict[str, str]
    ) -> Tuple[float, str]:
        """
        Calculate weighted confidence and determine dominant trend.
        
        Returns:
            (weighted_confidence, dominant_trend)
        """
        # Count votes for each direction
        long_votes = 0.0
        short_votes = 0.0
        neutral_votes = 0.0
        
        for interval, trend in tf_trends.items():
            weight = self.TF_WEIGHTS.get(interval, 0.0)
            confidence = tf_scores.get(interval, 0.0)
            
            weighted_conf = confidence * weight
            
            if trend == "LONG":
                long_votes += weighted_conf
            elif trend == "SHORT":
                short_votes += weighted_conf
            else:
                neutral_votes += weighted_conf
        
        # Determine dominant trend
        if long_votes > short_votes and long_votes > neutral_votes:
            dominant_trend = "LONG"
            weighted_confidence = long_votes
        elif short_votes > long_votes and short_votes > neutral_votes:
            dominant_trend = "SHORT"
            weighted_confidence = short_votes
        else:
            dominant_trend = "NEUTRAL"
            weighted_confidence = neutral_votes
        
        return (weighted_confidence, dominant_trend)
    
    def _get_dominant_timeframe(self, tf_scores: Dict[str, float]) -> str:
        """Get timeframe with highest weighted contribution"""
        max_contribution = 0.0
        dominant_tf = "4h"  # Default
        
        for interval, score in tf_scores.items():
            weight = self.TF_WEIGHTS.get(interval, 0.0)
            contribution = score * weight
            
            if contribution > max_contribution:
                max_contribution = contribution
                dominant_tf = interval
        
        return dominant_tf
    
    def _check_tf_alignment(self, tf_trends: Dict[str, str]) -> str:
        """
        Check alignment between timeframes.
        
        Returns:
            STRONG: All TFs agree
            MODERATE: 4H + 1H agree, 15M differs
            WEAK: Only 4H clear, others neutral/conflicting
            CONFLICTING: 4H vs 1H disagree
        """
        tf_4h = tf_trends.get("4h", "NEUTRAL")
        tf_1h = tf_trends.get("1h", "NEUTRAL")
        tf_15m = tf_trends.get("15m", "NEUTRAL")
        
        # All agree = STRONG
        if tf_4h == tf_1h == tf_15m and tf_4h != "NEUTRAL":
            return "STRONG"
        
        # 4H vs 1H conflict = CONFLICTING
        if tf_4h != "NEUTRAL" and tf_1h != "NEUTRAL" and tf_4h != tf_1h:
            return "CONFLICTING"
        
        # 4H + 1H agree, 15M differs = MODERATE
        if tf_4h == tf_1h and tf_4h != "NEUTRAL":
            return "MODERATE"
        
        # Only 4H clear = WEAK
        if tf_4h != "NEUTRAL" and (tf_1h == "NEUTRAL" or tf_15m == "NEUTRAL"):
            return "WEAK"
        
        # Default = WEAK
        return "WEAK"
    
    def _should_flip_decision(
        self,
        alignment: str,
        weighted_conf: float,
        dominant_trend: str,
        current_side: Optional[str]
    ) -> Tuple[bool, str]:
        """
        Decide if we should flip position.
        
        Returns:
            (should_flip, reason)
        """
        # No current position = no flip needed
        if not current_side:
            return (False, "No current position")
        
        # No clear direction = don't flip
        if dominant_trend == "NEUTRAL":
            return (False, "No clear trend direction")
        
        # Same direction = don't flip
        if dominant_trend == current_side:
            return (False, f"Already {current_side}, trend confirms")
        
        # CONFLICTING signals = don't flip (risky)
        if alignment == "CONFLICTING":
            return (False, "Conflicting timeframe signals")
        
        # STRONG alignment + opposite direction = FLIP
        if alignment == "STRONG" and weighted_conf >= 60.0:
            return (
                True,
                f"STRONG {alignment} alignment, {weighted_conf:.0f}% confidence, "
                f"trend reversed from {current_side} to {dominant_trend}"
            )
        
        # MODERATE alignment + high confidence = FLIP
        if alignment == "MODERATE" and weighted_conf >= 70.0:
            return (
                True,
                f"MODERATE alignment with high confidence ({weighted_conf:.0f}%), "
                f"4H+1H agree on {dominant_trend}"
            )
        
        # WEAK or low confidence = don't flip
        return (
            False,
            f"Alignment too weak ({alignment}) or confidence too low ({weighted_conf:.0f}%)"
        )


# Singleton instance
_analyzer: Optional[MultiTFWeightedAnalyzer] = None


def get_multi_tf_analyzer() -> MultiTFWeightedAnalyzer:
    """Get singleton analyzer instance"""
    global _analyzer
    if _analyzer is None:
        _analyzer = MultiTFWeightedAnalyzer()
    return _analyzer


def analyze_multi_tf_weighted(
    tf_contexts: Dict[str, Dict[str, Any]],
    current_side: Optional[str] = None
) -> WeightedTFAnalysis:
    """
    Convenience function for weighted multi-TF analysis.
    
    Args:
        tf_contexts: Dict mapping interval -> context data
        current_side: Current position side (LONG/SHORT) if any
        
    Returns:
        WeightedTFAnalysis with decision and confidence
    """
    analyzer = get_multi_tf_analyzer()
    return analyzer.analyze_multi_tf_weighted(tf_contexts, current_side)
