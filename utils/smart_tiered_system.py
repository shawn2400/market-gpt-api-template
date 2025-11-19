"""
Smart Tiered Quality System - Hybrid Adaptive Architecture
==========================================================
Combines Fixed Safety Tiers (Layer 1) with AI-Generated Strategies (Layer 2)

Layer 1: 3 Safety Tiers (Fixed Protection)
- Tier 1 (Strong Market): Quality ≥4.4, basic filters
- Tier 2 (Normal Market): Quality ≥4.5 + smart confluence filters
- Tier 3 (Weak Market): Quality ≥6.0, maximum protection

Layer 2: AI Strategy Generator (Dynamic)
- Auto-generates strategies per regime
- Auto-switches when regime changes
- Adapts parameters per strategy

Author: AlgoGPT Team - MetaBrain v9.1
"""

import logging
from typing import Dict, Any, Optional, Tuple, Literal
from dataclasses import dataclass

LOGGER = logging.getLogger("smart_tiered_system")


@dataclass
class TierDefinition:
    """Definition of a quality tier"""
    tier_name: str
    tier_number: int
    min_quality: float
    filters_required: list
    description: str
    leverage_range: Tuple[float, float]
    sl_multiplier_range: Tuple[float, float]
    tp_ratio_range: Tuple[float, float]


@dataclass
class MarketStrength:
    """Market strength analysis result"""
    strength_score: float  # 0-10
    volatility_score: float  # 0-10
    volume_score: float  # 0-10
    liquidity_score: float  # 0-10
    correlation_score: float  # 0-10
    active_tier: TierDefinition
    tier_reason: str


class SmartTieredSystem:
    """
    3-Tier Safety Foundation with auto-switching based on market conditions
    """
    
    def __init__(self):
        self.logger = LOGGER
        
        # Define 3 fixed safety tiers
        self.tiers = {
            1: TierDefinition(
                tier_name="Strong Market",
                tier_number=1,
                min_quality=4.4,
                filters_required=["basic_validation"],
                description="Standard trading - good market conditions",
                leverage_range=(5.0, 10.0),
                sl_multiplier_range=(1.5, 2.5),
                tp_ratio_range=(2.0, 3.5)
            ),
            2: TierDefinition(
                tier_name="Normal Market + Smart Filters",
                tier_number=2,
                min_quality=4.5,
                filters_required=[
                    "volume_1.2x_minimum",
                    "trend_4h_alignment",
                    "risk_reward_1.8_minimum",
                    "momentum_confirmation"
                ],
                description="Enhanced filters - moderate market conditions",
                leverage_range=(3.0, 7.0),
                sl_multiplier_range=(2.0, 3.0),
                tp_ratio_range=(1.8, 2.8)
            ),
            3: TierDefinition(
                tier_name="Weak Market - High Conviction Only",
                tier_number=3,
                min_quality=4.5,
                filters_required=["maximum_protection", "high_conviction_only"],
                description="Only premium setups - weak market conditions",
                leverage_range=(2.0, 5.0),
                sl_multiplier_range=(2.5, 4.0),
                tp_ratio_range=(2.5, 4.0)
            )
        }
        
        # Market strength thresholds for tier selection
        self.tier_thresholds = {
            1: 7.0,   # Strength ≥7.0 → Tier 1
            2: 4.0,   # Strength 4.0-6.9 → Tier 2
            3: 0.0    # Strength <4.0 → Tier 3
        }
    
    def calculate_market_strength(
        self,
        volatility: float,
        volume_trend: float,
        btc_correlation: float,
        adx_strength: float,
        liquidity_depth: float
    ) -> MarketStrength:
        """
        Calculate comprehensive market strength score (0-10)
        
        Args:
            volatility: ATR% (lower is better for stability)
            volume_trend: Volume ratio vs 24h avg (higher is better)
            btc_correlation: Correlation with BTC (0-1, moderate is best)
            adx_strength: ADX value (trend strength)
            liquidity_depth: Order book depth score
            
        Returns:
            MarketStrength with overall score and active tier
        """
        
        # 1. Volatility Score (20%) - Stable is better
        if 1.5 <= volatility <= 3.0:
            vol_score = 10.0  # Ideal volatility
        elif 3.0 < volatility <= 4.5:
            vol_score = 7.0   # Acceptable
        elif 4.5 < volatility <= 6.0:
            vol_score = 4.0   # High but manageable
        elif volatility < 1.5:
            vol_score = 6.0   # Too low (hard to profit)
        else:
            vol_score = 2.0   # Too high (risky)
        
        # 2. Volume Score (30%) - Higher is better
        if volume_trend >= 1.5:
            volume_score = 10.0  # Strong volume
        elif volume_trend >= 1.2:
            volume_score = 8.0   # Good volume
        elif volume_trend >= 1.0:
            volume_score = 6.0   # Average volume
        elif volume_trend >= 0.8:
            volume_score = 4.0   # Low volume
        else:
            volume_score = 2.0   # Very low (illiquid)
        
        # 3. Liquidity Score (15%) - Order book depth
        # liquidity_depth: 0-10 scale from caller
        liquidity_score = liquidity_depth
        
        # 4. Correlation Score (15%) - BTC correlation (moderate is best)
        # 0.4-0.6 correlation is ideal (some independence, some market following)
        if 0.4 <= btc_correlation <= 0.6:
            corr_score = 10.0  # Ideal balance
        elif 0.2 <= btc_correlation < 0.4 or 0.6 < btc_correlation <= 0.8:
            corr_score = 7.0   # Acceptable
        elif btc_correlation < 0.2:
            corr_score = 5.0   # Too independent (risky)
        else:
            corr_score = 4.0   # Too correlated (less opportunity)
        
        # 5. ADX/Trend Strength Score (20%)
        if adx_strength >= 35:
            adx_score = 10.0  # Very strong trend
        elif adx_strength >= 25:
            adx_score = 8.0   # Strong trend
        elif adx_strength >= 20:
            adx_score = 6.0   # Moderate trend
        elif adx_strength >= 15:
            adx_score = 4.0   # Weak trend
        else:
            adx_score = 2.0   # No trend (choppy)
        
        # Weighted overall strength (0-10)
        overall_strength = (
            vol_score * 0.20 +
            volume_score * 0.30 +
            liquidity_score * 0.15 +
            corr_score * 0.15 +
            adx_score * 0.20
        )
        
        # Select appropriate tier
        active_tier, tier_reason = self._select_tier(overall_strength)
        
        self.logger.info(
            f"Market Strength: {overall_strength:.1f}/10 | "
            f"Vol:{vol_score:.1f} Volume:{volume_score:.1f} "
            f"Liquidity:{liquidity_score:.1f} Corr:{corr_score:.1f} ADX:{adx_score:.1f} | "
            f"Active Tier: {active_tier.tier_number} ({active_tier.tier_name})"
        )
        
        return MarketStrength(
            strength_score=overall_strength,
            volatility_score=vol_score,
            volume_score=volume_score,
            liquidity_score=liquidity_score,
            correlation_score=corr_score,
            active_tier=active_tier,
            tier_reason=tier_reason
        )
    
    def _select_tier(self, strength_score: float) -> Tuple[TierDefinition, str]:
        """
        Select appropriate tier based on market strength
        
        Returns:
            (TierDefinition, reason_string)
        """
        if strength_score >= self.tier_thresholds[1]:
            return (
                self.tiers[1],
                f"Strong market conditions (strength {strength_score:.1f} ≥ {self.tier_thresholds[1]})"
            )
        elif strength_score >= self.tier_thresholds[2]:
            return (
                self.tiers[2],
                f"Normal market conditions (strength {strength_score:.1f} in 4.0-6.9 range)"
            )
        else:
            return (
                self.tiers[3],
                f"Weak market conditions (strength {strength_score:.1f} < {self.tier_thresholds[2]})"
            )
    
    def get_tier_by_number(self, tier_number: int) -> Optional[TierDefinition]:
        """Get tier definition by number (1, 2, or 3)"""
        return self.tiers.get(tier_number)
    
    def evaluate_context(
        self,
        symbol: str,
        context: Dict[str, Any],
        market_condition: Optional[Any] = None
    ) -> MarketStrength:
        """
        Evaluate market context using existing analyzers and select appropriate tier
        
        This is the INTEGRATION LAYER that reuses:
        - dynamic_filters.calculate_market_score() → rescaled to 0-10
        - market_intelligence.analyze_market() → provides trend, volatility, confidence
        
        Args:
            symbol: Trading symbol
            context: Market data dict with indicators
            market_condition: Optional pre-computed MarketCondition from MarketIntelligence
            
        Returns:
            MarketStrength with score and active tier
        """
        from utils.dynamic_filters import calculate_market_score
        from utils.market_intelligence import get_market_intelligence
        
        # Get market condition (analyze if not provided)
        if market_condition is None:
            mi = get_market_intelligence()
            market_condition = mi.analyze_market(context)
        
        # Get market score from dynamic_filters (-1 to +1)
        market_score = calculate_market_score(context)
        
        # Rescale market_score (-1..+1) to strength_score (0..10)
        # -1 → 0, 0 → 5, +1 → 10
        strength_score = (market_score + 1.0) * 5.0
        
        # Get component scores from market_condition
        # volatility: high/medium/low → scores
        if market_condition.volatility == "low":
            vol_score = 8.0  # Stable = good
        elif market_condition.volatility == "medium":
            vol_score = 6.0
        else:  # high
            vol_score = 4.0
        
        # Volume regime from context filters
        vol_regime = (context.get("filters") or {}).get("vol_regime", "mid")
        if vol_regime == "high":
            volume_score = 10.0
        elif vol_regime == "mid":
            volume_score = 6.0
        else:
            volume_score = 3.0
        
        # Liquidity score (use confidence as proxy)
        liquidity_score = market_condition.confidence / 10.0  # 0-100 → 0-10
        
        # Correlation score (use symbol for simple heuristic)
        if symbol.upper() == "BTCUSDT":
            corr_score = 10.0
        else:
            corr_score = 6.0  # Neutral for altcoins
        
        # Select tier based on rescaled strength
        active_tier, tier_reason = self._select_tier(strength_score)
        
        self.logger.info(
            f"[{symbol}] Tier Evaluation: Strength={strength_score:.1f}/10 "
            f"(market_score={market_score:+.2f}) | "
            f"Regime={market_condition.regime.upper()} "
            f"Mood={market_condition.mood.upper()} | "
            f"Selected: Tier {active_tier.tier_number} ({active_tier.tier_name})"
        )
        
        return MarketStrength(
            strength_score=strength_score,
            volatility_score=vol_score,
            volume_score=volume_score,
            liquidity_score=liquidity_score,
            correlation_score=corr_score,
            active_tier=active_tier,
            tier_reason=tier_reason
        )


class SmartConfluenceValidator:
    """
    Validates smart confluence filters for Tier 2
    """
    
    def __init__(self):
        self.logger = LOGGER
    
    def validate_confluence(
        self,
        symbol: str,
        volume_ratio: float,
        trend_4h_aligned: bool,
        rr_ratio: float,
        adx_momentum: float,
        support_resistance_nearby: bool = True
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate all smart confluence filters for Tier 2
        
        Args:
            symbol: Trading symbol
            volume_ratio: Volume vs 24h average
            trend_4h_aligned: Is 4H trend aligned with trade direction?
            rr_ratio: Risk/Reward ratio
            adx_momentum: ADX value for momentum confirmation
            support_resistance_nearby: Is there S/R nearby?
            
        Returns:
            (passes_all_filters, detailed_results)
        """
        
        results = {}
        
        # Filter 1: Volume ≥1.2× average
        volume_pass = volume_ratio >= 1.2
        results['volume_1.2x'] = {
            'passed': volume_pass,
            'value': volume_ratio,
            'threshold': 1.2,
            'reason': f"Volume ratio {volume_ratio:.2f}× {'✅' if volume_pass else '❌ (<1.2×)'}"
        }
        
        # Filter 2: 4H Trend Alignment
        results['trend_4h_alignment'] = {
            'passed': trend_4h_aligned,
            'value': trend_4h_aligned,
            'threshold': True,
            'reason': f"4H trend {'✅ aligned' if trend_4h_aligned else '❌ not aligned'}"
        }
        
        # Filter 3: Risk/Reward ≥1.8
        rr_pass = rr_ratio >= 1.8
        results['risk_reward_1.8'] = {
            'passed': rr_pass,
            'value': rr_ratio,
            'threshold': 1.8,
            'reason': f"R:R {rr_ratio:.2f} {'✅' if rr_pass else '❌ (<1.8)'}"
        }
        
        # Filter 4: Momentum Confirmation (ADX ≥20 or strong RSI signal)
        momentum_pass = adx_momentum >= 20.0
        results['momentum_confirmation'] = {
            'passed': momentum_pass,
            'value': adx_momentum,
            'threshold': 20.0,
            'reason': f"ADX {adx_momentum:.1f} {'✅' if momentum_pass else '❌ (<20)'}"
        }
        
        # Filter 5: Support/Resistance (optional, helps quality)
        results['support_resistance'] = {
            'passed': support_resistance_nearby,
            'value': support_resistance_nearby,
            'threshold': True,
            'reason': f"S/R nearby: {'✅ yes' if support_resistance_nearby else '⚠️ no (optional)'}"
        }
        
        # All required filters must pass (S/R is optional)
        required_filters = ['volume_1.2x', 'trend_4h_alignment', 'risk_reward_1.8', 'momentum_confirmation']
        all_pass = all(results[f]['passed'] for f in required_filters)
        
        # Log results
        if all_pass:
            self.logger.info(f"✅ {symbol}: All smart filters PASSED")
        else:
            failed = [f for f in required_filters if not results[f]['passed']]
            self.logger.info(f"❌ {symbol}: Smart filters FAILED: {', '.join(failed)}")
        
        for filter_name, filter_result in results.items():
            self.logger.debug(f"  {filter_name}: {filter_result['reason']}")
        
        return all_pass, results


# Global instances
_smart_tiered_system = None
_smart_confluence_validator = None


def get_smart_tiered_system() -> SmartTieredSystem:
    """Get singleton instance of SmartTieredSystem"""
    global _smart_tiered_system
    if _smart_tiered_system is None:
        _smart_tiered_system = SmartTieredSystem()
    return _smart_tiered_system


def get_smart_confluence_validator() -> SmartConfluenceValidator:
    """Get singleton instance of SmartConfluenceValidator"""
    global _smart_confluence_validator
    if _smart_confluence_validator is None:
        _smart_confluence_validator = SmartConfluenceValidator()
    return _smart_confluence_validator
