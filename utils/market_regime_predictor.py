#!/usr/bin/env python3
"""
Market Regime Predictor
========================
Predict next market regime before it happens.
Uses simple but effective pattern recognition on price/volatility/trend.

Regimes: TRENDING → VOLATILE → CHOPPY → (repeat)
Goal: Predict 1-4 hours ahead, adjust strategy proactively
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger("market_regime_predictor")


class MarketRegimePredictor:
    """
    Predict market regime changes before they happen.
    Uses historical volatility + trend changes + momentum.
    """
    
    def __init__(self, lookback_periods: int = 24):
        self.lookback_periods = lookback_periods
        self.regime_history: deque = deque(maxlen=lookback_periods)
        self.atr_history: deque = deque(maxlen=lookback_periods)
        self.adx_history: deque = deque(maxlen=lookback_periods)
        
        logger.info("🔮 Market Regime Predictor initialized")
    
    def add_observation(
        self,
        regime: str,
        atr_pct: float,
        adx: float
    ) -> None:
        """
        Add market observation to history.
        
        Args:
            regime: Current regime (TRENDING/VOLATILE/CHOPPY)
            atr_pct: ATR as percentage
            adx: ADX value
        """
        self.regime_history.append(regime)
        self.atr_history.append(atr_pct)
        self.adx_history.append(adx)
    
    def predict_next_regime(self) -> Dict[str, Any]:
        """
        Predict next market regime (1-4 hours ahead).
        
        Returns:
            {
                "predicted_regime": str,
                "confidence": float (0-1),
                "transition_probability": float,
                "reasoning": str,
                "recommendation": str
            }
        """
        
        if len(self.regime_history) < 3:
            return {
                "predicted_regime": "UNKNOWN",
                "confidence": 0.0,
                "transition_probability": 0.0,
                "reasoning": "Not enough history",
                "recommendation": "Wait for more data"
            }
        
        current_regime = self.regime_history[-1]
        atr_trend = self._calculate_trend(list(self.atr_history))
        adx_trend = self._calculate_trend(list(self.adx_history))
        
        # Regime transition logic
        prediction = self._predict_transition(
            current_regime=current_regime,
            atr_trend=atr_trend,
            adx_trend=adx_trend
        )
        
        return prediction
    
    def _calculate_trend(self, values: List[float]) -> float:
        """
        Calculate trend direction.
        
        Returns:
            Positive: increasing trend
            Negative: decreasing trend
            ~0: no clear trend
        """
        if len(values) < 3:
            return 0.0
        
        recent = values[-3:]
        older = values[-6:-3] if len(values) >= 6 else values[:3]
        
        recent_avg = sum(recent) / len(recent)
        older_avg = sum(older) / len(older)
        
        if older_avg == 0:
            return 0.0
        
        return (recent_avg - older_avg) / older_avg
    
    def _predict_transition(
        self,
        current_regime: str,
        atr_trend: float,
        adx_trend: float
    ) -> Dict[str, Any]:
        """
        Predict next regime based on current state and trends.
        
        Logic:
        - TRENDING + falling ADX → may transition to CHOPPY
        - CHOPPY + rising ATR + rising ADX → may transition to VOLATILE/TRENDING
        - VOLATILE + rising ATR → may strengthen to CRASH
        """
        
        predicted = current_regime  # Default: no change
        confidence = 0.3
        reasoning = []
        
        # TRENDING transitions
        if current_regime == "TRENDING":
            if adx_trend < -0.05:  # ADX falling significantly
                predicted = "CHOPPY"
                confidence = 0.65
                reasoning.append("ADX declining → trend weakening")
            elif atr_trend > 0.10:  # ATR rising
                predicted = "VOLATILE"
                confidence = 0.55
                reasoning.append("ATR rising → volatility increasing")
        
        # CHOPPY transitions
        elif current_regime == "CHOPPY":
            if adx_trend > 0.10 and atr_trend > 0.05:
                predicted = "TRENDING"
                confidence = 0.70
                reasoning.append("ADX rising + ATR up → trend forming")
            elif atr_trend > 0.15:
                predicted = "VOLATILE"
                confidence = 0.60
                reasoning.append("ATR spiking → volatility incoming")
        
        # VOLATILE transitions
        elif current_regime == "VOLATILE":
            current_atr = self.atr_history[-1] if self.atr_history else 0
            if current_atr > 4.0:  # Extreme volatility
                predicted = "CRASH"
                confidence = 0.75
                reasoning.append("ATR extreme → crash risk")
            elif adx_trend > 0.08:
                predicted = "TRENDING"
                confidence = 0.60
                reasoning.append("ADX rising → trend emerging")
        
        recommendation = self._recommend_action(predicted, confidence)
        
        final_reasoning = " | ".join(reasoning) if reasoning else "No clear signals"
        
        return {
            "predicted_regime": predicted,
            "confidence": min(confidence, 0.95),
            "transition_probability": confidence,
            "reasoning": final_reasoning,
            "recommendation": recommendation
        }
    
    def _recommend_action(self, predicted_regime: str, confidence: float) -> str:
        """
        Recommend trading action based on prediction.
        """
        if confidence < 0.50:
            return "WAIT - Unclear signals"
        
        if predicted_regime == "TRENDING":
            return "🎯 PREPARE: Trending incoming - increase leverage"
        elif predicted_regime == "VOLATILE":
            return "⚠️  CAUTION: Volatility rising - reduce size"
        elif predicted_regime == "CHOPPY":
            return "🔄 ADAPT: Range-bound - grid/scalp strategies"
        elif predicted_regime == "CRASH":
            return "🚨 ALERT: Extreme volatility - REDUCE EXPOSURE"
        else:
            return "MAINTAIN: Current regime"
    
    def get_predictor_stats(self) -> Dict[str, Any]:
        """Get predictor statistics."""
        return {
            "history_length": len(self.regime_history),
            "recent_regimes": list(self.regime_history)[-5:],
            "avg_atr": sum(self.atr_history) / len(self.atr_history) if self.atr_history else 0,
            "avg_adx": sum(self.adx_history) / len(self.adx_history) if self.adx_history else 0
        }


# Global instance
_regime_predictor: Optional[MarketRegimePredictor] = None


def get_regime_predictor() -> MarketRegimePredictor:
    """Get or create global predictor."""
    global _regime_predictor
    if _regime_predictor is None:
        _regime_predictor = MarketRegimePredictor()
    return _regime_predictor
