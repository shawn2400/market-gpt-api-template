#!/usr/bin/env python3
# utils/regime_detection_engine.py
"""
🔥 UPGRADE #1 - Regime Detection Engine
========================================
Detects market regimes (TRENDING, CHOPPY, VOLATILE) and adapts trading parameters.
Part of 10 Advanced MetaBrain v9.1 Upgrades
"""

import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger("regime_detection")


@dataclass
class RegimeAnalysis:
    """Result of regime detection analysis"""
    regime: str  # TRENDING, CHOPPY, VOLATILE, UNKNOWN
    confidence: float  # 0-100
    indicators: Dict[str, float]
    recommendations: Dict[str, Any]


class RegimeDetectionEngine:
    """
    Detects market regimes from technical indicators.
    
    Regimes:
    - TRENDING: Clear directional bias (ADX > 25, DI+ or DI- strong)
    - CHOPPY: Range-bound market (ADX < 20, RSI neutral 40-60)
    - VOLATILE: High volatility with unclear direction (ATR spike, wide ranges)
    """
    
    def __init__(self):
        self.logger = logger
        logger.info("🔥 Regime Detection Engine initialized (MetaBrain v9.1)")
    
    def detect_regime(self, context: Dict[str, Any]) -> RegimeAnalysis:
        """
        Detect market regime from technical context.
        
        Args:
            context: Dict with keys:
                - adx: ADX value (0-100)
                - rsi: RSI value (0-100)
                - atr: ATR value
                - di_plus: DI+ value
                - di_minus: DI- value
                - close: Current price
                - ema_20: 20-period EMA
                - ema_50: 50-period EMA
        
        Returns:
            RegimeAnalysis with regime type and confidence
        """
        adx = context.get("adx", 20.0)
        rsi = context.get("rsi", 50.0)
        di_plus = context.get("di_plus", 20.0)
        di_minus = context.get("di_minus", 20.0)
        close = context.get("close", 0.0)
        ema_20 = context.get("ema_20", close)
        ema_50 = context.get("ema_50", close)
        
        # Ensure defaults
        if adx is None:
            adx = 20.0
        if rsi is None:
            rsi = 50.0
        if di_plus is None:
            di_plus = 20.0
        if di_minus is None:
            di_minus = 20.0
        if ema_20 is None:
            ema_20 = close
        if ema_50 is None:
            ema_50 = close
        
        indicators = {
            "adx": float(adx),
            "rsi": float(rsi),
            "di_plus": float(di_plus),
            "di_minus": float(di_minus)
        }
        
        # Regime detection logic
        if adx > 25 and (di_plus > 25 or di_minus > 25):
            regime = "TRENDING"
            confidence = min(100.0, (adx - 20) * 2.0)  # Scale to 0-100
        elif adx < 20 and 40 < rsi < 60:
            regime = "CHOPPY"
            confidence = 100.0 - abs(rsi - 50)  # Higher confidence when RSI neutral
        elif adx > 30:
            regime = "VOLATILE"
            confidence = min(100.0, (adx - 20) * 1.5)
        else:
            regime = "UNKNOWN"
            confidence = 50.0
        
        # Generate recommendations
        recommendations = self._get_recommendations(regime, context)
        
        self.logger.info(
            f"📊 Regime: {regime} ({confidence:.0f}%) | ADX={adx:.1f} RSI={rsi:.0f}"
        )
        
        return RegimeAnalysis(
            regime=regime,
            confidence=confidence,
            indicators=indicators,
            recommendations=recommendations
        )
    
    def _get_recommendations(self, regime: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Get trading recommendations based on regime"""
        if regime == "TRENDING":
            return {
                "strategy": "trend_following",
                "leverage_multiplier": 1.0,
                "min_quality": 6.0,
                "risk_reward_ratio": 1.5,
                "grid_enabled": False,
                "description": "Follow the trend with directional bias"
            }
        elif regime == "CHOPPY":
            return {
                "strategy": "range_trading",
                "leverage_multiplier": 0.7,
                "min_quality": 7.0,
                "risk_reward_ratio": 1.0,
                "grid_enabled": True,
                "description": "Use GRID trading to capture range bounces"
            }
        elif regime == "VOLATILE":
            return {
                "strategy": "breakout",
                "leverage_multiplier": 0.5,
                "min_quality": 8.0,
                "risk_reward_ratio": 2.0,
                "grid_enabled": False,
                "description": "Wait for breakout, tight stop loss"
            }
        else:
            return {
                "strategy": "neutral",
                "leverage_multiplier": 0.5,
                "min_quality": 7.5,
                "risk_reward_ratio": 1.2,
                "grid_enabled": False,
                "description": "Insufficient signal, trade defensively"
            }


# Singleton instance
_engine: Optional[RegimeDetectionEngine] = None


def get_regime_detector() -> RegimeDetectionEngine:
    """Get singleton regime detector instance"""
    global _engine
    if _engine is None:
        _engine = RegimeDetectionEngine()
    return _engine


__all__ = ["RegimeDetectionEngine", "get_regime_detector", "RegimeAnalysis"]
