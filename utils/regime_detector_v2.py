# -*- coding: utf-8 -*-
"""
Regime Detector v2 - Confidence-based Market Regime Detection
Detects 4 market regimes: TRENDING, CHOPPY, VOLATILE, SIDEWAYS
Returns regime label + confidence score (0..1)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict
import logging

log = logging.getLogger(__name__)


@dataclass
class RegimeResult:
    """Market regime detection result"""
    regime: str          # "TRENDING" | "CHOPPY" | "VOLATILE" | "SIDEWAYS"
    confidence: float    # 0..1
    features: Dict[str, float] = None


def detect_market_regime_v2(features: Dict[str, float]) -> RegimeResult:
    """
    Detect market regime based on technical features.
    
    Args:
        features: Dict with keys:
            - atr_pct: ATR as percentage of price (volatility)
            - adx: Average Directional Index (trend strength)
            - macd_slope: MACD momentum slope
            - rsi: Relative Strength Index
            
    Returns:
        RegimeResult with regime label and confidence
    """
    atr_pct = float(features.get("atr_pct", 0.0))
    adx     = float(features.get("adx", 0.0))
    macd_s  = float(features.get("macd_slope", 0.0))
    rsi     = float(features.get("rsi", 50.0))

    # Calculate regime scores (0..1)
    # TRENDING: High ADX + strong MACD + RSI at extremes
    trending = min(max((adx/48.0)*0.55 + (abs(macd_s)/5.0)*0.35 + (0.1 if (rsi<35 or rsi>65) else 0.0), 0), 1)
    
    # VOLATILE: High ATR percentage
    volatile = min(max(atr_pct/90.0, 0), 1)
    
    # CHOPPY: Low trend + moderate volatility
    choppy = max(0.0, 0.9 - trending - 0.3*volatile)
    
    # SIDEWAYS: Everything else
    sideways = max(0.0, 1.0 - max(trending, volatile, choppy))
    
    scores = {
        "TRENDING": trending,
        "VOLATILE": volatile,
        "CHOPPY": choppy,
        "SIDEWAYS": sideways
    }
    
    # Select regime with highest score
    regime = max(scores, key=scores.get)
    conf = float(scores[regime])
    
    # Lower confidence if scores are close (ambiguous)
    ordered = sorted(scores.values(), reverse=True)
    if len(ordered) > 1 and (ordered[0] - ordered[1]) < 0.12:
        conf *= 0.75
        log.info(f"[RegimeDetectorV2] Ambiguous regime, reducing confidence: {conf:.3f}")
    
    log.info(f"[RegimeDetectorV2] Detected {regime} (confidence={conf:.3f}, atr_pct={atr_pct:.2f}, adx={adx:.1f})")
    
    return RegimeResult(regime=regime, confidence=conf, features=features)
