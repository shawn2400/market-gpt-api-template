#!/usr/bin/env python3
"""
Smart Filter Dynamic Configuration Provider
===========================================
Provides regime-aware thresholds to Smart Filter, eliminating hardcoded constants
and enabling 100% automatic adaptation to market conditions.

Author: AlgoGPT Team
"""
import logging
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
    Provides dynamic Smart Filter thresholds based on Market Intelligence regime.
    
    Architecture:
    - CHOPPY markets → Lower thresholds (more opportunities)
    - TRENDING markets → Higher thresholds (quality over quantity)
    - VOLATILE markets → Medium thresholds
    - BTC correlation penalty adapts to mood/regime
    """
    
    # Regime-based threshold matrix
    REGIME_THRESHOLDS = {
        "choppy": {
            "volume_min": 0.1,      # Very low - choppy markets have low volume
            "quality_min": 2.0,      # Low - mean-reversion setups
            "direction_penalty": -1.0,  # Reduced from -1.5
            "btc_penalty_base": -0.5    # Reduced from -1.0
        },
        "sideways": {
            "volume_min": 0.15,
            "quality_min": 2.5,
            "direction_penalty": -1.2,
            "btc_penalty_base": -0.7
        },
        "trending": {
            "volume_min": 0.5,      # Higher - need confirmation
            "quality_min": 2.8,      # Relaxed from 4.0 - allow quality trades
            "direction_penalty": -1.3,  # Relaxed from -2.0
            "btc_penalty_base": -1.2    # Relaxed from -1.5
        },
        "volatile": {
            "volume_min": 0.3,
            "quality_min": 2.5,      # Relaxed from 3.0
            "direction_penalty": -1.2,  # Relaxed from -1.5
            "btc_penalty_base": -0.8    # Relaxed from -1.0
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
    
    def get_thresholds(self, 
                      regime: str, 
                      mood: str, 
                      confidence: float = 50.0,
                      symbol: str = "UNKNOWN") -> SmartFilterThresholds:
        """
        Get dynamic thresholds for given market conditions.
        
        Args:
            regime: Market regime (choppy, trending, sideways, volatile)
            mood: Market mood (bullish, bearish, neutral)
            confidence: Regime confidence (0-100)
            symbol: Trading symbol (for logging)
        
        Returns:
            SmartFilterThresholds with adaptive values
        """
        # Get base thresholds for regime (no caching - always fresh values)
        regime_lower = regime.lower()
        if regime_lower not in self.REGIME_THRESHOLDS:
            self.logger.warning(f"Unknown regime '{regime}', defaulting to choppy")
            regime_lower = "choppy"
        
        base = self.REGIME_THRESHOLDS[regime_lower]
        
        # Get mood modifier
        mood_lower = mood.lower()
        mood_modifier = self.MOOD_MODIFIERS.get(mood_lower, 1.0)
        
        # Calculate dynamic BTC penalty
        # Formula: base_penalty * mood_modifier * (confidence/100)
        # Higher confidence = stronger penalty
        btc_penalty = base["btc_penalty_base"] * mood_modifier * (confidence / 100.0)
        
        # Use base thresholds directly - no confidence multiplication!
        # Confidence already affects BTC penalty, that's enough dynamic adjustment
        thresholds = SmartFilterThresholds(
            volume_spike_min=base["volume_min"],
            quality_score_min=base["quality_min"],  # Direct value - no multiplication!
            btc_penalty=btc_penalty,
            direction_penalty=base["direction_penalty"],  # Direct value - no multiplication!
            regime=regime,
            mood=mood,
            confidence=confidence
        )
        
        self.logger.info(
            f"🎯 [{symbol}] Dynamic Thresholds: {regime.upper()} {mood.upper()} "
            f"→ Vol≥{thresholds.volume_spike_min:.2f}x, "
            f"Quality≥{thresholds.quality_score_min:.1f}, "
            f"BTC_penalty={thresholds.btc_penalty:.2f}, "
            f"Dir_penalty={thresholds.direction_penalty:.2f}"
        )
        
        return thresholds
    
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
