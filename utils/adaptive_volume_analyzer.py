#!/usr/bin/env python3
"""
Adaptive Volume Analyzer - Real-Time Market Volume Intelligence
================================================================
Measures actual market volume conditions and automatically adjusts
thresholds based on live data, not hard-coded assumptions.

Author: AlgoGPT Team
Philosophy: 100% Dynamic, 0% Hard-Coded
"""
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import statistics
import time

logger = logging.getLogger("algogpt.adaptive_volume")

@dataclass
class VolumeStats:
    """Market-wide volume statistics"""
    median_volume_ratio: float  # Median volume spike across all symbols
    p25_volume_ratio: float     # 25th percentile (aggressive/loose - low threshold, ~75% symbols pass)
    p75_volume_ratio: float     # 75th percentile (conservative/strict - high threshold, only top 25% pass)
    sample_size: int             # Number of symbols analyzed
    timestamp: float             # When this was calculated
    market_volume_regime: str    # LOW_VOLUME/NORMAL/HIGH_VOLUME
    low_volume_pct: float        # % of market with volume < 0.5x
    
    def __repr__(self):
        return (f"VolumeStats(median={self.median_volume_ratio:.3f}x, "
                f"p25={self.p25_volume_ratio:.3f}x, p75={self.p75_volume_ratio:.3f}x, "
                f"regime={self.market_volume_regime}, low_vol={self.low_volume_pct:.0f}%, "
                f"n={self.sample_size})")


class AdaptiveVolumeAnalyzer:
    """
    Analyzes real-time market volume conditions and provides
    dynamic thresholds based on actual market behavior.
    
    Key Features:
    - Measures median/percentile volume ratios across all active symbols
    - Auto-adjusts thresholds to match current market conditions
    - Safety guardrails prevent extreme values
    - Cache with TTL to avoid excessive API calls
    """
    
    # Safety Guardrails (Absolute Limits)
    MIN_VOLUME_THRESHOLD = 0.03  # Never go below 3% (prevent garbage)
    MAX_VOLUME_THRESHOLD = 0.50  # Never go above 50% (prevent missing all trades)
    
    # Percentile Selection Strategy
    # IMPORTANT: Percentiles work INVERSELY to threshold strictness!
    # - p75 = CONSERVATIVE (high threshold, only top 25% volume symbols pass)
    # - median = BALANCED (medium threshold, ~50% of symbols pass)
    # - p25 = AGGRESSIVE (low threshold, ~75% of symbols pass)
    DEFAULT_PERCENTILE_STRATEGY = "p75"  # Conservative by default (strict filtering)
    
    # Market Volume Regime Detection Thresholds
    LOW_VOLUME_MARKET_THRESHOLD = 0.60   # If >60% of symbols have volume < 0.5x
    HIGH_VOLUME_MARKET_THRESHOLD = 0.30  # If <30% of symbols have volume < 0.5x
    
    # Market Regime Auto-Adjustment Multipliers
    MARKET_REGIME_MULTIPLIERS = {
        "LOW_VOLUME": 0.15,    # Reduce thresholds by 85% in low-volume markets (aggressive adaptation)
        "NORMAL": 1.0,         # Standard thresholds
        "HIGH_VOLUME": 1.5     # Increase thresholds by 50% in high-volume markets
    }
    
    # Cache TTL (seconds)
    CACHE_TTL = 300  # 5 minutes - refresh market stats periodically
    
    def __init__(self):
        self.logger = logger
        self._cache: Optional[VolumeStats] = None
        self._cache_timestamp: float = 0
    
    def get_adaptive_volume_threshold(self, 
                                      regime: str,
                                      percentile_strategy: str = DEFAULT_PERCENTILE_STRATEGY,
                                      force_refresh: bool = False) -> float:
        """
        Get volume threshold adapted to current market conditions.
        
        Args:
            regime: Market regime (choppy, trending, sideways, volatile)
            percentile_strategy: "p75" (conservative/strict), "median" (balanced), "p25" (aggressive/loose)
            force_refresh: Force cache refresh (default: False)
        
        Returns:
            Adaptive volume threshold (e.g., 0.08 for 8% volume spike)
        """
        # Get current market volume stats
        stats = self._get_volume_stats(force_refresh)
        
        if stats is None:
            self.logger.warning(f"Volume stats unavailable, using safe fallback")
            return self._get_fallback_threshold(regime)
        
        # Select threshold based on strategy (validate and normalize)
        VALID_STRATEGIES = ["p25", "median", "p75"]
        strategy_normalized = percentile_strategy.lower()
        
        if strategy_normalized not in VALID_STRATEGIES:
            self.logger.error(f"❌ Invalid percentile strategy '{percentile_strategy}', defaulting to p75 (conservative)")
            strategy_normalized = "p75"
        
        if strategy_normalized == "p25":
            raw_threshold = stats.p25_volume_ratio
        elif strategy_normalized == "median":
            raw_threshold = stats.median_volume_ratio
        else:  # p75
            raw_threshold = stats.p75_volume_ratio
        
        # Apply regime-based multiplier
        # CHOPPY: 0.6x (more permissive)
        # TRENDING: 1.0x (standard)
        # VOLATILE: 1.2x (more selective)
        regime_multipliers = {
            "choppy": 0.6,
            "sideways": 0.8,
            "trending": 1.0,
            "volatile": 1.2
        }
        regime_multiplier = regime_multipliers.get(regime.lower(), 1.0)
        
        # 🆕 APPLY MARKET VOLUME REGIME AUTO-ADJUSTMENT
        # This is the KEY feature - automatically adjust thresholds based on market-wide volume
        market_regime_multiplier = self.MARKET_REGIME_MULTIPLIERS.get(stats.market_volume_regime, 1.0)
        
        # Combine both multipliers (trading regime × market volume regime)
        combined_multiplier = regime_multiplier * market_regime_multiplier
        adaptive_threshold = raw_threshold * combined_multiplier
        
        # Apply safety guardrails
        final_threshold = max(
            self.MIN_VOLUME_THRESHOLD,
            min(self.MAX_VOLUME_THRESHOLD, adaptive_threshold)
        )
        
        self.logger.info(
            f"📊 Adaptive Volume Threshold: {regime.upper()} @ {percentile_strategy} "
            f"→ {final_threshold:.3f}x (raw: {raw_threshold:.3f}x, "
            f"regime_mult: {regime_multiplier:.2f}x, market_mult: {market_regime_multiplier:.2f}x, "
            f"market_regime: {stats.market_volume_regime})"
        )
        
        return final_threshold
    
    def _get_volume_stats(self, force_refresh: bool = False) -> Optional[VolumeStats]:
        """
        Get market-wide volume statistics from cache or fresh calculation.
        
        Args:
            force_refresh: Force recalculation (ignore cache)
        
        Returns:
            VolumeStats or None if calculation fails
        """
        # Check cache validity
        now = time.time()
        if not force_refresh and self._cache is not None:
            cache_age = now - self._cache_timestamp
            if cache_age < self.CACHE_TTL:
                self.logger.debug(f"Using cached volume stats (age: {cache_age:.0f}s)")
                return self._cache
        
        # Calculate fresh stats
        self.logger.info("Calculating fresh market volume statistics...")
        stats = self._calculate_volume_stats()
        
        if stats is not None:
            self._cache = stats
            self._cache_timestamp = now
            self.logger.info(f"✅ Volume stats updated: {stats}")
        
        return stats
    
    def _calculate_volume_stats(self) -> Optional[VolumeStats]:
        """
        Calculate volume statistics from live Binance 24h ticker data.
        
        Strategy:
        - Use quoteVolume from 24h ticker (actual USDT volume)
        - Compare against median of all symbols to get relative volume
        - This gives us a market-normalized volume metric
        
        Returns:
            VolumeStats or None if API call fails
        """
        try:
            # Use the same trending_utils fetch function
            from utils.trending_utils import _fetch_24h
            
            # Fetch 24h ticker for all USDT futures
            tickers = _fetch_24h("https://fapi.binance.com/fapi/v1/ticker/24hr")
            
            if not tickers:
                self.logger.warning("No ticker data available")
                return None
            
            # Extract volumes for all USDT symbols
            volumes: List[float] = []
            
            for ticker in tickers:
                symbol = ticker.get("symbol", "")
                if not symbol.endswith("USDT"):
                    continue
                
                # Get 24h quote volume (in USDT)
                volume = float(ticker.get("quoteVolume", 0))
                
                if volume > 0:
                    volumes.append(volume)
            
            if len(volumes) < 10:
                self.logger.warning(f"Insufficient volume data: {len(volumes)} symbols")
                return None
            
            # Calculate percentiles on RAW volumes (not normalized)
            # Then normalize thresholds against median for comparison
            volumes.sort()
            
            # Calculate percentiles on raw volumes
            market_median_volume = statistics.median(volumes)
            market_p25_volume = self._percentile(volumes, 25)
            market_p75_volume = self._percentile(volumes, 75)
            
            # Normalize percentiles by median to get volume ratios
            # IMPORTANT: Lower threshold = MORE symbols pass (counterintuitive!)
            # 
            # Why? Because we check: symbol_volume/median >= threshold
            # - Low threshold (0.3) → symbol needs volume ≥ 30% of median → many symbols pass
            # - High threshold (1.5) → symbol needs volume ≥ 150% of median → few symbols pass
            #
            # Strategy mapping:
            # - p25: Uses 25th percentile volume / median = LOW threshold → LOOSE filter (more trades)
            # - median: Uses median volume / median = 1.0 threshold → BALANCED filter
            # - p75: Uses 75th percentile volume / median = HIGH threshold → STRICT filter (fewer trades)
            
            # Note: p25 < median < p75, so p25/median < 1.0 < p75/median
            median = 1.0  # By definition when comparing to itself
            p25 = market_p25_volume / market_median_volume  # < 1.0 (LOOSE - more symbols pass)
            p75 = market_p75_volume / market_median_volume  # > 1.0 (STRICT - fewer symbols pass)
            
            # 🆕 MARKET VOLUME REGIME DETECTION
            # Calculate % of market with low volume (< 0.5x median)
            low_volume_threshold = market_median_volume * 0.5
            low_volume_count = sum(1 for v in volumes if v < low_volume_threshold)
            low_volume_pct = (low_volume_count / len(volumes)) * 100.0
            
            # Determine market regime
            if low_volume_pct > self.LOW_VOLUME_MARKET_THRESHOLD * 100:
                market_regime = "LOW_VOLUME"
            elif low_volume_pct < self.HIGH_VOLUME_MARKET_THRESHOLD * 100:
                market_regime = "HIGH_VOLUME"
            else:
                market_regime = "NORMAL"
            
            self.logger.info(f"📊 Market Volume Regime: {market_regime} ({low_volume_pct:.0f}% symbols < 0.5x median)")
            
            return VolumeStats(
                median_volume_ratio=median,
                p25_volume_ratio=p25,
                p75_volume_ratio=p75,
                sample_size=len(volumes),
                timestamp=time.time(),
                market_volume_regime=market_regime,
                low_volume_pct=low_volume_pct
            )
            
        except Exception as e:
            self.logger.error(f"Failed to calculate volume stats: {e}", exc_info=True)
            return None
    
    @staticmethod
    def _percentile(data: List[float], percentile: float) -> float:
        """Calculate percentile from sorted data"""
        if not data:
            return 0.0
        k = (len(data) - 1) * (percentile / 100.0)
        f = int(k)
        c = f + 1 if f < len(data) - 1 else f
        if f == c:
            return data[f]
        d0 = data[f] * (c - k)
        d1 = data[c] * (k - f)
        return d0 + d1
    
    def _get_fallback_threshold(self, regime: str) -> float:
        """
        Safe fallback thresholds when market data unavailable.
        These are conservative defaults based on historical averages.
        """
        fallback_map = {
            "choppy": 0.05,
            "sideways": 0.10,
            "trending": 0.12,
            "volatile": 0.15
        }
        threshold = fallback_map.get(regime.lower(), 0.08)
        self.logger.info(f"Using fallback threshold: {regime.upper()} → {threshold:.3f}x")
        return threshold
    
    def clear_cache(self):
        """Force cache refresh on next call"""
        self._cache = None
        self._cache_timestamp = 0
        self.logger.debug("Volume stats cache cleared")


# Singleton instance
_analyzer = None

def get_adaptive_volume_threshold(regime: str, 
                                  percentile_strategy: str = "p75",
                                  force_refresh: bool = False) -> float:
    """
    Get adaptive volume threshold for given regime.
    
    Usage:
        threshold = get_adaptive_volume_threshold("trending", "p75")  # Conservative (default)
        if volume_ratio >= threshold:
            # Pass Stage 1
    
    Args:
        regime: Market regime (choppy, trending, sideways, volatile)
        percentile_strategy: "p75" (conservative/strict - default), "median" (balanced), "p25" (aggressive/loose)
        force_refresh: Force fresh calculation (default: False)
    
    Returns:
        Adaptive volume threshold (0.03 - 0.50)
    """
    global _analyzer
    if _analyzer is None:
        _analyzer = AdaptiveVolumeAnalyzer()
    return _analyzer.get_adaptive_volume_threshold(regime, percentile_strategy, force_refresh)
