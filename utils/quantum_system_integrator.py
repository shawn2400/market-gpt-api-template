#!/usr/bin/env python3
"""
Quantum System Integrator
===========================
Plugs the 3 Quantum engines into the existing strategy pipeline.
- Pattern Recognition → confidence boost
- Adaptive Scoring → dynamic weights  
- Regime Predictor → proactive adjustments

This is a WRAPPER that makes quantum engines work with existing system.
"""

import logging
from typing import Dict, Any, Optional

from utils.quantum_pattern_engine import get_quantum_pattern_engine
from utils.adaptive_confidence_scorer import get_adaptive_scorer
from utils.market_regime_predictor import get_regime_predictor

logger = logging.getLogger("quantum_system_integrator")


class QuantumSystemIntegrator:
    """
    Unifies all 3 Quantum engines and provides easy integration points.
    """
    
    def __init__(self):
        self.pattern_engine = get_quantum_pattern_engine()
        self.confidence_scorer = get_adaptive_scorer()
        self.regime_predictor = get_regime_predictor()
        
        logger.info("🚀 Quantum System Integrator initialized")
    
    def enhance_trade_proposal(
        self,
        symbol: str,
        quality_score: float,
        market_score: float,
        volatility_score: float,
        adx: float,
        market_regime: str,
        atr_pct: float
    ) -> Dict[str, Any]:
        """
        Enhance trade proposal using all 3 Quantum engines.
        
        Returns:
            {
                "enhanced_quality": float,
                "pattern_boost": float,
                "adaptive_confidence": float,
                "regime_prediction": dict,
                "final_recommendation": str
            }
        """
        
        # 1. Get pattern boost (if pattern has proven track record)
        pattern_boost, pattern_reason = self.pattern_engine.get_pattern_confidence_boost(
            symbol=symbol,
            quality_score=quality_score,
            market_regime=market_regime,
            atr_pct=atr_pct,
            adx=adx
        )
        
        # 2. Calculate adaptive confidence with dynamic weights
        adaptive_result = self.confidence_scorer.calculate_adaptive_confidence(
            quality_score=quality_score,
            market_score=market_score,
            volatility_score=volatility_score,
            adx_score=adx,
            pattern_boost=pattern_boost,
            market_regime=market_regime
        )
        
        # 3. Predict next regime
        regime_pred = self.regime_predictor.predict_next_regime()
        
        # 4. Combine into final recommendation
        enhanced_quality = min(10.0, quality_score + (pattern_boost * 2.0))
        
        final_rec = self._build_final_recommendation(
            enhanced_quality=enhanced_quality,
            adaptive_confidence=adaptive_result["final_confidence"],
            regime_prediction=regime_pred,
            pattern_reason=pattern_reason
        )
        
        return {
            "enhanced_quality": enhanced_quality,
            "pattern_boost": pattern_boost,
            "pattern_reason": pattern_reason,
            "adaptive_confidence": adaptive_result["final_confidence"],
            "adaptive_weights": adaptive_result["adaptive_weights"],
            "regime_prediction": regime_pred,
            "final_recommendation": final_rec
        }
    
    def log_completed_trade(
        self,
        symbol: str,
        entry_price: float,
        exit_price: float,
        quality_score: float,
        market_regime: str,
        atr_pct: float,
        adx: Optional[float],
        result: str  # "win" or "loss"
    ) -> None:
        """
        Log completed trade to all engines for learning.
        """
        # Log to pattern engine for learning
        self.pattern_engine.add_trade(
            symbol=symbol,
            entry_price=entry_price,
            exit_price=exit_price,
            quality_score=quality_score,
            market_regime=market_regime,
            atr_pct=atr_pct,
            adx=adx,
            result=result
        )
        
        # Update confidence scorer's regime performance
        self.confidence_scorer.update_regime_performance(
            market_regime=market_regime,
            result=result
        )
        
        # Add observation to regime predictor
        self.regime_predictor.add_observation(
            regime=market_regime,
            atr_pct=atr_pct,
            adx=adx or 0.0
        )
        
        logger.info(f"📊 Trade logged to quantum engines: {symbol} {result.upper()}")
    
    def _build_final_recommendation(
        self,
        enhanced_quality: float,
        adaptive_confidence: float,
        regime_prediction: Dict[str, Any],
        pattern_reason: str
    ) -> str:
        """Build human-readable final recommendation."""
        
        rec_parts = []
        
        # Quality assessment
        if enhanced_quality >= 8.5:
            rec_parts.append("🟢 HIGH QUALITY")
        elif enhanced_quality >= 7.0:
            rec_parts.append("🟡 MEDIUM QUALITY")
        else:
            rec_parts.append("🔴 LOW QUALITY")
        
        # Pattern assessment
        if "pattern proven" in pattern_reason.lower():
            rec_parts.append("✅ Pattern proven")
        elif "avoiding" in pattern_reason.lower():
            rec_parts.append("❌ Pattern avoidance")
        
        # Regime assessment
        if regime_prediction["confidence"] > 0.7:
            rec_parts.append(f"🔮 {regime_prediction['predicted_regime']} incoming")
        
        return " | ".join(rec_parts)
    
    def get_quantum_stats(self) -> Dict[str, Any]:
        """Get all quantum engine statistics."""
        return {
            "pattern_engine": self.pattern_engine.get_learning_stats(),
            "confidence_scorer": self.confidence_scorer.get_scorer_stats(),
            "regime_predictor": self.regime_predictor.get_predictor_stats()
        }


# Global instance
_quantum_integrator: Optional[QuantumSystemIntegrator] = None


def get_quantum_system() -> QuantumSystemIntegrator:
    """Get or create global quantum integrator."""
    global _quantum_integrator
    if _quantum_integrator is None:
        _quantum_integrator = QuantumSystemIntegrator()
    return _quantum_integrator
