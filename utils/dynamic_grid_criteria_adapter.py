# utils/dynamic_grid_criteria_adapter.py
"""
Dynamic GRID Criteria Adapter - Regime-Aware Threshold Adjustment
==================================================================
Adapts GRID trading criteria based on market regime:
- CHOPPY/SIDEWAYS: Relax thresholds (GRID optimal)
- TRENDING: Tighten thresholds (GRID risky)
- VOLATILE: Moderate thresholds

Features:
- Redis-backed caching & 15min debounce
- Safety guardrails (absolute minimums)
- Fail-closed design (falls back to static thresholds)
- Audit trail persistence

Author: AlgoGPT Team
"""

import json
import logging
import time
from typing import Dict, Optional, Literal
from dataclasses import dataclass, asdict

logger = logging.getLogger("algogpt.grid_criteria")


@dataclass
class GridThresholds:
    """GRID trading thresholds"""
    min_volume: float
    max_atr_pct: float
    max_spread_bps: float
    min_liquidity: float
    regime: str
    timestamp: float
    source: str  # "dynamic" or "static_fallback"


class DynamicGridCriteriaAdapter:
    """
    Adjusts GRID criteria based on market regime with safety guardrails.
    
    Design:
    - Aggregated regime from BTC/ETH (not per-symbol to avoid API spam)
    - 15min debounce prevents whipsaw
    - Absolute minimums enforced regardless of regime
    - Redis cache for performance
    - Fail-closed fallback to static thresholds
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
        
        # Redis keys
        self.active_regime_key = "grid:regime:active"
        self.criteria_key = "grid:criteria:active"
        self.market_regime_key = "market:regime:global"
        
        # Base thresholds (current DynamicGridApprover settings)
        self.base_thresholds = {
            'min_volume': 40_000_000,      # $40M
            'max_atr_pct': 0.05,           # 5%
            'max_spread_bps': 15,          # 15bps
            'min_liquidity': 100_000       # $100k
        }
        
        # Regime multipliers
        self.regime_multipliers = {
            'choppy': {
                'volume_mult': 0.7,    # Relax volume (×0.7 = $28M)
                'liquidity_mult': 0.7, # Relax liquidity (×0.7 = $70k)
                'atr_mult': 1.3,       # Allow higher ATR (×1.3 = 6.5%)
                'spread_mult': 1.2     # Allow wider spread (×1.2 = 18bps)
            },
            'sideways': {
                'volume_mult': 0.7,
                'liquidity_mult': 0.7,
                'atr_mult': 1.3,
                'spread_mult': 1.2
            },
            'trending': {
                'volume_mult': 1.2,    # Tighten volume (×1.2 = $48M)
                'liquidity_mult': 1.2, # Tighten liquidity (×1.2 = $120k)
                'atr_mult': 0.8,       # Lower ATR (×0.8 = 4%)
                'spread_mult': 0.9     # Tighter spread (×0.9 = 13.5bps)
            },
            'volatile': {
                'volume_mult': 1.0,    # Neutral
                'liquidity_mult': 1.0,
                'atr_mult': 1.1,       # Slightly higher ATR (×1.1 = 5.5%)
                'spread_mult': 1.0
            }
        }
        
        # Safety guardrails (absolute minimums)
        self.guardrails = {
            'min_volume': 20_000_000,      # $20M minimum
            'max_atr_pct': 0.07,           # 7% maximum
            'max_spread_bps': 25,          # 25bps maximum
            'min_liquidity': 75_000        # $75k minimum
        }
        
        # Debounce settings
        self.debounce_sec = 900  # 15 minutes
        
        logger.info(
            f"DynamicGridCriteriaAdapter initialized | "
            f"Debounce: {self.debounce_sec}s, "
            f"Guardrails: Vol≥${self.guardrails['min_volume']/1_000_000:.0f}M, "
            f"Liq≥${self.guardrails['min_liquidity']/1_000:.0f}k, "
            f"ATR≤{self.guardrails['max_atr_pct']*100:.0f}%, "
            f"Spread≤{self.guardrails['max_spread_bps']}bps"
        )
    
    def get_adjusted_thresholds(self, force_refresh: bool = False) -> GridThresholds:
        """
        Get regime-adjusted GRID thresholds with caching and debounce.
        
        Args:
            force_refresh: Skip cache and recalculate
            
        Returns:
            GridThresholds with adjusted values
        """
        try:
            # Try cache first (unless force refresh)
            if not force_refresh:
                cached = self._get_cached_criteria()
                if cached:
                    logger.debug(
                        f"📊 Using cached GRID criteria: {cached.regime.upper()}, "
                        f"age={time.time()-cached.timestamp:.0f}s"
                    )
                    return cached
            
            # Get current market regime
            regime = self._get_market_regime()
            
            # Check debounce (prevent rapid regime changes)
            # CRITICAL FIX: On cold start (no cache), bypass debounce to set initial thresholds
            cached_for_debounce = self._get_cached_criteria()
            if not cached_for_debounce:
                logger.info(f"🆕 Cold start - bypassing debounce, setting initial thresholds for {regime.upper()}")
            elif not self._should_update_regime(regime):
                logger.debug(f"⏳ Regime change debounced: {regime} (waiting for 15min)")
                # Return current cached (guaranteed to exist since we just checked)
                return cached_for_debounce
            
            # Calculate adjusted thresholds
            adjusted = self._apply_regime_multipliers(regime)
            
            # Enforce safety guardrails
            clamped = self._clamp_to_guardrails(adjusted)
            
            # Create thresholds object
            thresholds = GridThresholds(
                min_volume=clamped['min_volume'],
                max_atr_pct=clamped['max_atr_pct'],
                max_spread_bps=clamped['max_spread_bps'],
                min_liquidity=clamped['min_liquidity'],
                regime=regime,
                timestamp=time.time(),
                source='dynamic'
            )
            
            # Save to Redis (cache + audit trail)
            self._save_criteria(thresholds)
            
            logger.info(
                f"✅ GRID criteria updated: {regime.upper()} | "
                f"Vol≥${thresholds.min_volume/1_000_000:.0f}M, "
                f"Liq≥${thresholds.min_liquidity/1_000:.0f}k, "
                f"ATR≤{thresholds.max_atr_pct*100:.1f}%, "
                f"Spread≤{thresholds.max_spread_bps}bps"
            )
            
            return thresholds
            
        except Exception as e:
            logger.error(f"❌ Failed to get adjusted thresholds: {e}", exc_info=True)
            return self._get_base_thresholds_fallback()
    
    def _get_market_regime(self) -> str:
        """
        Get aggregated market regime from BTC/ETH composite.
        Falls back to 'sideways' if unavailable.
        """
        try:
            # Try to get cached global regime
            regime_data = self.redis.get(self.market_regime_key)
            if regime_data:
                regime = json.loads(regime_data).get('regime', 'sideways')
                logger.debug(f"📊 Global regime: {regime.upper()}")
                return regime.lower()
            
            # Fallback: analyze BTC as market proxy
            logger.debug("🔍 No global regime - using BTC as proxy")
            regime = self._analyze_btc_regime()
            
            # Cache result
            self.redis.setex(
                self.market_regime_key,
                600,  # 10min TTL
                json.dumps({
                    'regime': regime,
                    'timestamp': time.time(),
                    'source': 'btc_proxy'
                })
            )
            
            return regime
            
        except Exception as e:
            logger.warning(f"Failed to get market regime: {e}")
            return 'sideways'  # Safe default
    
    def _analyze_btc_regime(self) -> str:
        """
        Quick regime detection using BTC price action.
        Simple fallback when MarketIntelligence unavailable.
        """
        try:
            from utils.binance_client import get_client
            client = get_client()
            
            if not client:
                return 'sideways'
            
            ticker = client.futures_ticker(symbol='BTCUSDT')
            price_change_pct = abs(float(ticker.get('priceChangePercent', 0)))
            
            # Simple heuristic
            if price_change_pct > 5:
                return 'volatile'
            elif price_change_pct > 2:
                return 'trending'
            else:
                return 'choppy'
                
        except:
            return 'sideways'
    
    def _should_update_regime(self, new_regime: str) -> bool:
        """
        Check if regime change should be applied (15min debounce).
        """
        try:
            data = self.redis.get(self.active_regime_key)
            if not data:
                # No active regime - allow update
                return True
            
            active = json.loads(data)
            current_regime = active.get('regime')
            last_change = active.get('timestamp', 0)
            
            if current_regime == new_regime:
                # Same regime - no change needed
                return False
            
            # Different regime - check debounce
            time_since_change = time.time() - last_change
            if time_since_change < self.debounce_sec:
                logger.debug(
                    f"⏳ Regime debounce: {current_regime}→{new_regime} "
                    f"blocked ({time_since_change:.0f}s < {self.debounce_sec}s)"
                )
                return False
            
            logger.info(
                f"🔄 Regime change: {current_regime.upper()} → {new_regime.upper()} "
                f"(after {time_since_change:.0f}s)"
            )
            return True
            
        except Exception as e:
            logger.debug(f"Debounce check failed: {e}")
            return True  # Fail-open
    
    def _apply_regime_multipliers(self, regime: str) -> Dict:
        """Apply regime-specific multipliers to base thresholds."""
        multipliers = self.regime_multipliers.get(
            regime.lower(),
            {'volume_mult': 1.0, 'liquidity_mult': 1.0, 'atr_mult': 1.0, 'spread_mult': 1.0}
        )
        
        # Clip multipliers to reasonable range (0.6-1.4)
        multipliers = {
            k: max(0.6, min(1.4, v))
            for k, v in multipliers.items()
        }
        
        adjusted = {
            'min_volume': self.base_thresholds['min_volume'] * multipliers['volume_mult'],
            'min_liquidity': self.base_thresholds['min_liquidity'] * multipliers['liquidity_mult'],
            'max_atr_pct': self.base_thresholds['max_atr_pct'] * multipliers['atr_mult'],
            'max_spread_bps': self.base_thresholds['max_spread_bps'] * multipliers['spread_mult']
        }
        
        return adjusted
    
    def _clamp_to_guardrails(self, thresholds: Dict) -> Dict:
        """
        Enforce absolute safety guardrails.
        Ensures thresholds never go below/above safety limits.
        """
        clamped = {
            'min_volume': max(thresholds['min_volume'], self.guardrails['min_volume']),
            'min_liquidity': max(thresholds['min_liquidity'], self.guardrails['min_liquidity']),
            'max_atr_pct': min(thresholds['max_atr_pct'], self.guardrails['max_atr_pct']),
            'max_spread_bps': min(thresholds['max_spread_bps'], self.guardrails['max_spread_bps'])
        }
        
        # Log if clamping occurred
        if clamped != thresholds:
            logger.info("🛡️ Guardrails enforced (clamped thresholds)")
        
        return clamped
    
    def _save_criteria(self, thresholds: GridThresholds):
        """Save criteria to Redis for caching and audit trail."""
        try:
            data = asdict(thresholds)
            
            # Save active criteria
            self.redis.setex(
                self.criteria_key,
                1200,  # 20min TTL
                json.dumps(data)
            )
            
            # Update active regime timestamp (for debounce)
            self.redis.setex(
                self.active_regime_key,
                3600,  # 1h TTL
                json.dumps({
                    'regime': thresholds.regime,
                    'timestamp': thresholds.timestamp
                })
            )
            
            logger.debug("💾 Saved GRID criteria to Redis")
            
        except Exception as e:
            logger.warning(f"Failed to save criteria: {e}")
    
    def _get_cached_criteria(self) -> Optional[GridThresholds]:
        """Get cached criteria from Redis."""
        try:
            data = self.redis.get(self.criteria_key)
            if not data:
                return None
            
            criteria_dict = json.loads(data)
            
            # Check if cache is fresh (< 20min)
            age = time.time() - criteria_dict.get('timestamp', 0)
            if age > 1200:  # 20min
                logger.debug(f"Cache expired ({age:.0f}s old)")
                return None
            
            return GridThresholds(**criteria_dict)
            
        except Exception as e:
            logger.debug(f"Failed to get cached criteria: {e}")
            return None
    
    def _get_base_thresholds_fallback(self) -> GridThresholds:
        """
        Return BASE thresholds as fallback (not strict guardrails).
        CRITICAL: This uses the relaxed base values ($40M, 5% ATR) not the strict guardrails ($20M, 7% ATR).
        """
        logger.warning("⚠️ Using BASE thresholds fallback (adapter failed, not strict guardrails)")
        return GridThresholds(
            min_volume=self.base_thresholds['min_volume'],       # $40M (relaxed)
            max_atr_pct=self.base_thresholds['max_atr_pct'],     # 5% (relaxed)
            max_spread_bps=self.base_thresholds['max_spread_bps'], # 15bps (relaxed)
            min_liquidity=self.base_thresholds['min_liquidity'], # $100k (relaxed)
            regime='sideways',  # Safe neutral default
            timestamp=time.time(),
            source='base_fallback'
        )
    
    def get_stats(self) -> Dict:
        """Get adapter statistics for monitoring."""
        try:
            cached = self._get_cached_criteria()
            active_regime = self.redis.get(self.active_regime_key)
            
            return {
                'cached_criteria': asdict(cached) if cached else None,
                'active_regime': json.loads(active_regime) if active_regime else None,
                'config': {
                    'base_thresholds': self.base_thresholds,
                    'guardrails': self.guardrails,
                    'debounce_sec': self.debounce_sec
                }
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {}


# Singleton accessor
_criteria_adapter: Optional[DynamicGridCriteriaAdapter] = None

def get_criteria_adapter():
    """Get or create criteria adapter singleton."""
    global _criteria_adapter
    if _criteria_adapter is None:
        from utils.redis_client import get_redis
        redis_client = get_redis()
        if not redis_client:
            logger.error("Redis not available - criteria adapter disabled")
            return None
        _criteria_adapter = DynamicGridCriteriaAdapter(redis_client)
    return _criteria_adapter
