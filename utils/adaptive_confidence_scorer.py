#!/usr/bin/env python3
"""
Adaptive Confidence Scorer
===========================
Uses recent trade history to dynamically adjust confidence weights.
Smart, practical, learns from what actually works.

Features:
- Adjusts quality/market/regime weights based on recent performance
- Market regime detection impacts scoring
- Continuously learns what combinations work best
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger("adaptive_confidence_scorer")


class AdaptiveConfidenceScorer:
    """
    Dynamically adjust confidence scoring based on market conditions and trade history.
    """
    
    def __init__(self):
        # Default weights (can be tuned)
        self.base_weights = {
            "quality": 0.35,      # Trade quality score
            "market": 0.25,       # Market regime
            "volatility": 0.15,   # ATR volatility
            "adx": 0.15,          # Trend strength
            "pattern": 0.10       # Pattern history
        }
        
        # Adaptive multipliers (updated based on market performance)
        self.weight_multipliers = {
            "quality": 1.0,
            "market": 1.0,
            "volatility": 1.0,
            "adx": 1.0,
            "pattern": 1.0
        }
        
        # Market regime performance tracking
        self.regime_performance = {
            "TRENDING": {"wins": 0, "losses": 0},
            "VOLATILE": {"wins": 0, "losses": 0},
            "CHOPPY": {"wins": 0, "losses": 0},
            "CRASH": {"wins": 0, "losses": 0}
        }
        
        logger.info("🎯 Adaptive Confidence Scorer initialized")
    
    def calculate_adaptive_confidence(
        self,
        quality_score: float,
        market_score: float,
        volatility_score: float,
        adx_score: float,
        pattern_boost: float = 0.0,
        market_regime: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calculate confidence with adaptive weighting.
        
        Args:
            quality_score: Base quality (0-10)
            market_score: Market regime score (0-10)
            volatility_score: Volatility score (0-10)
            adx_score: ADX strength score (0-10)
            pattern_boost: Pattern confidence boost (-1.0 to 1.0)
            market_regime: Current regime for tracking
        
        Returns:
            {
                "final_confidence": float (0-10),
                "breakdown": dict,
                "adaptive_weights": dict,
                "reasoning": str
            }
        """
        
        # Apply adaptive multipliers to weights
        adaptive_weights = {}
        for key, base_weight in self.base_weights.items():
            multiplier = self.weight_multipliers.get(key, 1.0)
            adaptive_weights[key] = base_weight * multiplier
        
        # Normalize weights to sum to 1.0
        total_weight = sum(adaptive_weights.values())
        for key in adaptive_weights:
            adaptive_weights[key] /= total_weight
        
        # Calculate weighted confidence
        confidence_components = {
            "quality": quality_score * adaptive_weights["quality"],
            "market": market_score * adaptive_weights["market"],
            "volatility": volatility_score * adaptive_weights["volatility"],
            "adx": adx_score * adaptive_weights["adx"],
            "pattern": (5.0 + pattern_boost * 5.0) * adaptive_weights["pattern"]  # Convert boost to score
        }
        
        final_confidence = sum(confidence_components.values())
        final_confidence = max(0, min(10, final_confidence))  # Clamp 0-10
        
        # Build reasoning
        strongest_factors = sorted(
            confidence_components.items(),
            key=lambda x: x[1],
            reverse=True
        )[:2]
        
        reasoning_parts = [
            f"Quality {quality_score:.1f}" if quality_score >= 7 else None,
            f"Regime: {market_regime}" if market_regime else None,
            f"Pattern: +{pattern_boost*100:.0f}%" if pattern_boost > 0.1 else None
        ]
        reasoning = " | ".join([r for r in reasoning_parts if r])
        
        return {
            "final_confidence": final_confidence,
            "breakdown": confidence_components,
            "adaptive_weights": adaptive_weights,
            "strongest_factors": strongest_factors,
            "reasoning": reasoning
        }
    
    def update_regime_performance(
        self,
        market_regime: str,
        result: str  # "win" or "loss"
    ) -> None:
        """
        Track which regimes are performing well.
        Gradually shift weights to favor profitable regimes.
        """
        if market_regime not in self.regime_performance:
            return
        
        if result == "win":
            self.regime_performance[market_regime]["wins"] += 1
        else:
            self.regime_performance[market_regime]["losses"] += 1
        
        # Recalculate market weight multiplier
        self._update_weight_multipliers()
    
    def _update_weight_multipliers(self) -> None:
        """
        Dynamically adjust weights based on recent performance.
        Trending regimes performing well? Boost market weight.
        Quality scores correlating with wins? Boost quality weight.
        """
        # Calculate win rates by regime
        regime_win_rates = {}
        for regime, perf in self.regime_performance.items():
            total = perf["wins"] + perf["losses"]
            if total > 0:
                regime_win_rates[regime] = perf["wins"] / total
        
        # If TRENDING performing significantly better, boost market weight
        if regime_win_rates.get("TRENDING", 0.5) > 0.65:
            self.weight_multipliers["market"] = 1.3  # 30% boost
        elif regime_win_rates.get("TRENDING", 0.5) < 0.40:
            self.weight_multipliers["market"] = 0.7  # 30% reduce
        else:
            self.weight_multipliers["market"] = 1.0
        
        logger.debug(
            f"🔄 Weights updated | Market: {self.weight_multipliers['market']:.2f}x | "
            f"Trending win%: {regime_win_rates.get('TRENDING', 0.5):.1%}"
        )
    
    def get_scorer_stats(self) -> Dict[str, Any]:
        """Get current scoring statistics."""
        return {
            "base_weights": self.base_weights,
            "adaptive_multipliers": self.weight_multipliers,
            "regime_performance": self.regime_performance
        }


# Global instance
_adaptive_scorer: Optional[AdaptiveConfidenceScorer] = None


def get_adaptive_scorer() -> AdaptiveConfidenceScorer:
    """Get or create global scorer."""
    global _adaptive_scorer
    if _adaptive_scorer is None:
        _adaptive_scorer = AdaptiveConfidenceScorer()
    return _adaptive_scorer
