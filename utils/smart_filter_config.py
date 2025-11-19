#!/usr/bin/env python3
"""
Smart Filter Dynamic Configuration Provider v2.0
================================================
100% ADAPTIVE SYSTEM - Provides regime-aware thresholds that automatically
adjust to real-time market conditions, not hard-coded assumptions.

Key Features:
- Adaptive volume thresholds based on live market data
- Regime-aware quality/penalty adjustments
- Safety guardrails prevent extreme values
- Zero manual intervention required

Author: AlgoGPT Team
Philosophy: Measure reality, adapt automatically
"""
import logging
import os
from typing import Dict, Any, Tuple
from dataclasses import dataclass

logger = logging.getLogger("algogpt.smart_filter_config")

@dataclass
class SmartFilterThresholds:
    """Dynamic thresholds based on market regime"""
    volume_spike_min: float
    quality_score_min: float
    btc_penalty: float
    direction_penalty: float
    regime: str
    mood: str
    confidence: float


class SmartFilterConfigProvider:
    """
    100% Adaptive Smart Filter Configuration Provider
    
    Features:
    - ADAPTIVE VOLUME: Real-time volume thresholds based on market-wide analysis
    - Regime-aware quality/penalty adjustments
    - Safety guardrails with smart fallbacks
    - Zero manual tuning required
    
    Environment Variables:
    - ADAPTIVE_VOLUME_ENABLED (default: 1) - Enable adaptive volume analysis
    - VOLUME_PERCENTILE_STRATEGY (default: p75) - p75 (strict/conservative), median (balanced), p25 (loose/aggressive)
    """
    
    # Regime-based threshold matrix (FALLBACK ONLY - adaptive overrides volume_min)
    # These are safety defaults used when adaptive system unavailable
    REGIME_THRESHOLDS = {
        "choppy": {
            "volume_min_fallback": 0.05,  # Fallback only
            "quality_min": 1.8,
            "direction_penalty": -0.8,
            "btc_penalty_base": -0.4
        },
        "sideways": {
            "volume_min_fallback": 0.10,  # Fallback only
            "quality_min": 2.5,
            "direction_penalty": -1.2,
            "btc_penalty_base": -0.7
        },
        "trending": {
            "volume_min_fallback": 0.12,  # Fallback only (was 0.20, too high)
            "quality_min": 2.0,
            "direction_penalty": -1.0,
            "btc_penalty_base": -1.0
        },
        "volatile": {
            "volume_min_fallback": 0.15,  # Fallback only
            "quality_min": 2.2,
            "direction_penalty": -1.2,
            "btc_penalty_base": -0.8
        }
    }
    
    # Mood-based BTC penalty modifiers
    MOOD_MODIFIERS = {
        "bullish": 0.7,   # Reduce penalty in bullish mood
        "neutral": 1.0,   # Standard penalty
        "bearish": 1.3    # Increase penalty in bearish mood
    }
    
    def __init__(self):
        self.logger = logger
        self._cache: Dict[str, SmartFilterThresholds] = {}
        
        # Adaptive volume configuration
        self.adaptive_volume_enabled = os.getenv("ADAPTIVE_VOLUME_ENABLED", "1") == "1"
        raw_strategy = os.getenv("VOLUME_PERCENTILE_STRATEGY", "p75")
        
        # Validate and normalize percentile strategy
        VALID_STRATEGIES = ["p25", "median", "p75"]
        strategy_normalized = raw_strategy.lower()
        
        if strategy_normalized not in VALID_STRATEGIES:
            self.logger.error(f"❌ Invalid VOLUME_PERCENTILE_STRATEGY '{raw_strategy}', defaulting to p75 (conservative)")
            self.volume_percentile_strategy = "p75"
        else:
            self.volume_percentile_strategy = strategy_normalized
            if strategy_normalized != "p75":
                self.logger.info(f"📊 Volume Percentile Strategy: {strategy_normalized.upper()}")
            # No log for p75 (default/conservative - expected)
    
    def get_thresholds(self, 
                      regime: str, 
                      mood: str, 
                      confidence: float = 50.0,
                      symbol: str = "UNKNOWN") -> SmartFilterThresholds:
        """
        Get 100% ADAPTIVE thresholds for given market conditions.
        
        NEW v2.0 Features:
        - Volume threshold adapts to real-time market conditions
        - Measures actual volume distribution across all symbols
        - Auto-adjusts to low/high volume environments
        - Safety fallbacks if adaptive system fails
        
        Args:
            regime: Market regime (choppy, trending, sideways, volatile)
            mood: Market mood (bullish, bearish, neutral)
            confidence: Regime confidence (0-100)
            symbol: Trading symbol (for logging)
        
        Returns:
            SmartFilterThresholds with 100% adaptive values
        """
        # Get base thresholds for regime
        regime_lower = regime.lower()
        if regime_lower not in self.REGIME_THRESHOLDS:
            self.logger.warning(f"Unknown regime '{regime}', defaulting to choppy")
            regime_lower = "choppy"
        
        base = self.REGIME_THRESHOLDS[regime_lower]
        
        # Get mood modifier
        mood_lower = mood.lower()
        mood_modifier = self.MOOD_MODIFIERS.get(mood_lower, 1.0)
        
        # Calculate dynamic BTC penalty
        btc_penalty = base["btc_penalty_base"] * mood_modifier * (confidence / 100.0)
        
        # 🆕 ADAPTIVE VOLUME THRESHOLD (v2.0)
        # Try to get real-time market-based threshold, fallback to static if fails
        volume_threshold = self._get_adaptive_volume_threshold(regime_lower)
        
        thresholds = SmartFilterThresholds(
            volume_spike_min=volume_threshold,  # 🆕 ADAPTIVE!
            quality_score_min=base["quality_min"],
            btc_penalty=btc_penalty,
            direction_penalty=base["direction_penalty"],
            regime=regime,
            mood=mood,
            confidence=confidence
        )
        
        self.logger.info(
            f"🎯 [{symbol}] {'ADAPTIVE' if self.adaptive_volume_enabled else 'STATIC'} Thresholds: "
            f"{regime.upper()} {mood.upper()} → Vol≥{thresholds.volume_spike_min:.3f}x, "
            f"Quality≥{thresholds.quality_score_min:.1f}, "
            f"BTC_penalty={thresholds.btc_penalty:.2f}, "
            f"Dir_penalty={thresholds.direction_penalty:.2f}"
        )
        
        return thresholds
    
    def _get_adaptive_volume_threshold(self, regime: str) -> float:
        """
        Get volume threshold adapted to real-time market conditions.
        
        Priority:
        1. Try adaptive analyzer (measures real market volume)
        2. Fallback to static threshold if adaptive fails
        
        Args:
            regime: Market regime
        
        Returns:
            Volume threshold (0.03 - 0.50)
        """
        # If adaptive disabled, use fallback immediately
        if not self.adaptive_volume_enabled:
            fallback = self.REGIME_THRESHOLDS[regime]["volume_min_fallback"]
            self.logger.debug(f"Adaptive volume DISABLED, using fallback: {fallback:.3f}x")
            return fallback
        
        # Try adaptive volume analyzer
        try:
            from utils.adaptive_volume_analyzer import get_adaptive_volume_threshold
            
            adaptive_threshold = get_adaptive_volume_threshold(
                regime=regime,
                percentile_strategy=self.volume_percentile_strategy,
                force_refresh=False  # Use cache if fresh
            )
            
            self.logger.debug(
                f"✅ Adaptive volume threshold: {adaptive_threshold:.3f}x "
                f"(strategy={self.volume_percentile_strategy})"
            )
            return adaptive_threshold
            
        except Exception as e:
            # Fallback to static if adaptive fails
            fallback = self.REGIME_THRESHOLDS[regime]["volume_min_fallback"]
            self.logger.warning(
                f"⚠️ Adaptive volume failed: {e}, using fallback: {fallback:.3f}x"
            )
            return fallback
    
    def get_thresholds_from_context(self, ctx: Dict[str, Any]) -> SmartFilterThresholds:
        """
        Extract regime/mood from context OR query Market Intelligence.
        Falls back to safe defaults if market intelligence not available.
        
        Priority:
        1. Use regime/mood from ctx if available
        2. Call Market Intelligence to analyze current conditions
        3. Fallback to CHOPPY/NEUTRAL (safe defaults)
        
        Args:
            ctx: Market context with market data
        
        Returns:
            SmartFilterThresholds
        """
        symbol = ctx.get("symbol", "UNKNOWN")
        
        # Option 1: Use regime/mood from ctx if already analyzed
        if "regime" in ctx and "mood" in ctx:
            regime = ctx.get("regime", "choppy")
            mood = ctx.get("mood", "neutral")
            confidence = ctx.get("confidence", 50.0)
            
            self.logger.debug(f"[{symbol}] Using regime from ctx: {regime}/{mood}")
            return self.get_thresholds(regime, mood, confidence, symbol)
        
        # Option 2: Query Market Intelligence for fresh analysis
        try:
            from utils.market_intelligence import MarketIntelligence
            mi = MarketIntelligence()
            
            # Run market analysis
            condition = mi.analyze_market(ctx)
            
            self.logger.info(
                f"[{symbol}] Fresh Market Intelligence: {condition.regime.upper()}/{condition.mood.upper()} "
                f"(confidence={condition.confidence:.0f}%)"
            )
            
            return self.get_thresholds(
                condition.regime, 
                condition.mood, 
                condition.confidence, 
                symbol
            )
        except Exception as e:
            self.logger.warning(f"[{symbol}] Market Intelligence unavailable: {e}, using safe defaults")
        
        # Option 3: Fallback to safe CHOPPY defaults
        self.logger.info(f"[{symbol}] Fallback: Using CHOPPY/NEUTRAL defaults")
        return self.get_thresholds("choppy", "neutral", 50.0, symbol)
    
    def clear_cache(self):
        """Clear threshold cache (call when market conditions change significantly)"""
        self._cache.clear()
        self.logger.debug("Smart Filter threshold cache cleared")


def get_dynamic_thresholds(regime: str, mood: str, confidence: float = 50.0, symbol: str = "UNKNOWN") -> SmartFilterThresholds:
    """
    Get dynamic Smart Filter thresholds based on market regime.
    
    Usage:
        thresholds = get_dynamic_thresholds("choppy", "neutral", 75.0, "BTCUSDT")
        if volume_ratio >= thresholds.volume_spike_min:
            # Pass Stage 1
    """
    provider = SmartFilterConfigProvider()  # Fresh instance - no caching!
    return provider.get_thresholds(regime, mood, confidence, symbol)


def get_thresholds_from_context(ctx: Dict[str, Any]) -> SmartFilterThresholds:
    """
    Get thresholds from market context dictionary.
    
    Usage:
        thresholds = get_thresholds_from_context(market_ctx)
    """
    provider = SmartFilterConfigProvider()  # Fresh instance - always uses latest REGIME_THRESHOLDS!
    return provider.get_thresholds_from_context(ctx)
