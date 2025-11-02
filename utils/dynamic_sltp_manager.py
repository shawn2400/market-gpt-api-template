# utils/dynamic_sltp_manager.py
"""
Dynamic SL/TP Manager with Monte Carlo Simulation
==================================================
Advanced stop-loss and take-profit placement using probabilistic analysis.

Features:
- Monte Carlo simulation for optimal SL placement
- Probability-adjusted TP levels
- Regime-specific exit strategies (trending vs choppy vs volatile)
- Risk/Reward optimization

Author: AlgoGPT Team
Level: Hedge Fund Grade
"""

from __future__ import annotations

import logging
import random
from typing import Dict, Any, Optional, Tuple, List, Literal
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger("dynamic_sltp")


@dataclass
class SLTPRecommendation:
    """Stop-loss and take-profit recommendations"""
    sl_price: float
    tp1_price: float
    tp2_price: float
    tp3_price: float
    sl_confidence: float  # 0-100
    tp_probabilities: List[float]  # Probability of hitting each TP
    regime_strategy: str  # trending|choppy|volatile
    risk_reward: float
    expected_value: float  # EV of the trade


class DynamicSLTPManager:
    """
    Calculates optimal SL/TP placement using Monte Carlo simulation
    and market regime analysis.
    
    **Methodology:**
    1. Run Monte Carlo price simulation based on ATR and volatility
    2. Calculate probability of hitting various price levels
    3. Optimize SL to balance risk vs premature exit
    4. Set TP levels with high probability of achievement
    5. Adjust for market regime (wider stops in choppy markets)
    """
    
    def __init__(self):
        self.logger = logger
        
        # Monte Carlo parameters
        self.num_simulations = 1000  # Number of price paths to simulate
        self.max_periods = 100  # Simulate up to 100 periods (e.g., candles)
    
    def calculate_sltp(
        self,
        symbol: str,
        side: Literal["LONG", "SHORT"],
        entry_price: float,
        atr: float,
        atr_pct: float,
        market_regime: Literal["trending", "sideways", "choppy", "volatile"],
        market_mood: Literal["bullish", "bearish", "neutral"],
        trend_strength: float,  # 0-100
        target_rr: float = 1.5,  # Target risk/reward
        volatility_class: Literal["high", "medium", "low"] = "medium"
    ) -> SLTPRecommendation:
        """
        Calculate optimal SL/TP levels using Monte Carlo simulation.
        
        Args:
            symbol: Trading symbol
            side: LONG or SHORT
            entry_price: Entry price
            atr: Average True Range (absolute)
            atr_pct: ATR as percentage of price
            market_regime: Current market regime
            market_mood: Current market mood
            trend_strength: Trend strength (0-100)
            target_rr: Target risk/reward ratio
            volatility_class: Volatility classification
            
        Returns:
            SLTPRecommendation with optimal levels
        """
        # Run Monte Carlo simulation
        stop_probabilities, target_probabilities = self._run_monte_carlo(
            entry_price, atr, atr_pct, side, market_regime, volatility_class
        )
        
        # Calculate optimal SL based on regime
        sl_price, sl_confidence = self._calculate_optimal_sl(
            entry_price, atr, side, market_regime, stop_probabilities, trend_strength
        )
        
        # Calculate probability-adjusted TP levels
        tp1_price, tp2_price, tp3_price, tp_probs = self._calculate_optimal_tps(
            entry_price, sl_price, side, atr, target_rr, target_probabilities,
            market_regime, market_mood, trend_strength
        )
        
        # Calculate metrics
        risk = abs(entry_price - sl_price)
        reward1 = abs(tp1_price - entry_price)
        rr = reward1 / risk if risk > 0 else 0.0
        
        # Expected value calculation
        ev = self._calculate_expected_value(
            entry_price, sl_price, [tp1_price, tp2_price, tp3_price],
            tp_probs, side
        )
        
        # Determine regime-specific strategy
        regime_strategy = self._get_regime_strategy(market_regime, trend_strength)
        
        recommendation = SLTPRecommendation(
            sl_price=round(sl_price, 8),
            tp1_price=round(tp1_price, 8),
            tp2_price=round(tp2_price, 8),
            tp3_price=round(tp3_price, 8),
            sl_confidence=sl_confidence,
            tp_probabilities=tp_probs,
            regime_strategy=regime_strategy,
            risk_reward=round(rr, 2),
            expected_value=round(ev, 2)
        )
        
        self.logger.info(
            f"🎯 Dynamic SL/TP [{symbol} {side}]: "
            f"SL={sl_price:.8f} (conf={sl_confidence:.0f}%), "
            f"TP1={tp1_price:.8f} (prob={tp_probs[0]:.0f}%), "
            f"RR={rr:.2f}, EV=${ev:.2f}, Strategy={regime_strategy}"
        )
        
        return recommendation
    
    def _run_monte_carlo(
        self,
        entry_price: float,
        atr: float,
        atr_pct: float,
        side: str,
        regime: str,
        volatility: str
    ) -> Tuple[Dict[float, float], Dict[float, float]]:
        """
        Run Monte Carlo simulation to estimate probabilities.
        
        Returns:
            (stop_probabilities, target_probabilities)
            Each is a dict mapping price level -> probability of hitting
        """
        # Adjust volatility for regime
        if regime == "volatile":
            vol_multiplier = 1.5
        elif regime == "choppy":
            vol_multiplier = 1.2
        elif regime == "sideways":
            vol_multiplier = 0.8
        else:  # trending
            vol_multiplier = 1.0
        
        # Adjust for volatility class
        if volatility == "high":
            vol_multiplier *= 1.3
        elif volatility == "low":
            vol_multiplier *= 0.7
        
        effective_vol = atr_pct / 100.0 * vol_multiplier
        
        # Run simulations
        stop_hits = {
            0.5: 0, 1.0: 0, 1.5: 0, 2.0: 0, 2.5: 0, 3.0: 0
        }  # ATR multiples for stops
        
        target_hits = {
            1.0: 0, 1.5: 0, 2.0: 0, 2.5: 0, 3.0: 0, 4.0: 0
        }  # ATR multiples for targets
        
        for _ in range(self.num_simulations):
            price = entry_price
            hit_stop = False
            hit_target = {mult: False for mult in target_hits.keys()}
            
            # Simulate price path
            for period in range(self.max_periods):
                # Random price change (Geometric Brownian Motion approximation)
                change_pct = np.random.normal(0, effective_vol)
                price *= (1 + change_pct)
                
                # Check if we hit stops or targets
                for stop_mult in stop_hits.keys():
                    stop_level = entry_price - (atr * stop_mult) if side == "LONG" else entry_price + (atr * stop_mult)
                    if (side == "LONG" and price <= stop_level) or (side == "SHORT" and price >= stop_level):
                        if not hit_stop:
                            stop_hits[stop_mult] += 1
                            hit_stop = True
                
                for target_mult in target_hits.keys():
                    target_level = entry_price + (atr * target_mult) if side == "LONG" else entry_price - (atr * target_mult)
                    if (side == "LONG" and price >= target_level) or (side == "SHORT" and price <= target_level):
                        if not hit_target[target_mult]:
                            target_hits[target_mult] += 1
                            hit_target[target_mult] = True
        
        # Convert counts to probabilities
        stop_probs = {mult: (count / self.num_simulations) for mult, count in stop_hits.items()}
        target_probs = {mult: (count / self.num_simulations) for mult, count in target_hits.items()}
        
        return (stop_probs, target_probs)
    
    def _calculate_optimal_sl(
        self,
        entry_price: float,
        atr: float,
        side: str,
        regime: str,
        stop_probabilities: Dict[float, float],
        trend_strength: float
    ) -> Tuple[float, float]:
        """
        Calculate optimal SL based on regime and probabilities.
        
        Returns:
            (sl_price, confidence_score)
        """
        # Regime-specific SL multipliers
        if regime == "trending" and trend_strength > 60:
            # Strong trend = tighter stops (trend continuation expected)
            sl_mult = 1.5
        elif regime == "choppy":
            # Choppy = wider stops (avoid noise)
            sl_mult = 2.5
        elif regime == "volatile":
            # Volatile = wider stops (large swings expected)
            sl_mult = 3.0
        elif regime == "sideways":
            # Sideways = medium stops (range-bound)
            sl_mult = 2.0
        else:
            # Default
            sl_mult = 2.0
        
        # Calculate SL price
        if side == "LONG":
            sl_price = entry_price - (atr * sl_mult)
        else:  # SHORT
            sl_price = entry_price + (atr * sl_mult)
        
        # Confidence = inverse of stop probability
        # (lower probability of hitting stop = higher confidence)
        stop_prob = stop_probabilities.get(sl_mult, 0.5)
        confidence = (1.0 - stop_prob) * 100.0
        
        return (sl_price, confidence)
    
    def _calculate_optimal_tps(
        self,
        entry_price: float,
        sl_price: float,
        side: str,
        atr: float,
        target_rr: float,
        target_probabilities: Dict[float, float],
        regime: str,
        mood: str,
        trend_strength: float
    ) -> Tuple[float, float, float, List[float]]:
        """
        Calculate probability-adjusted TP levels.
        
        Returns:
            (tp1, tp2, tp3, [prob1, prob2, prob3])
        """
        risk = abs(entry_price - sl_price)
        
        # Base TP levels using target RR
        if side == "LONG":
            tp1_base = entry_price + (risk * target_rr)
            tp2_base = entry_price + (risk * target_rr * 1.5)
            tp3_base = entry_price + (risk * target_rr * 2.0)
        else:  # SHORT
            tp1_base = entry_price - (risk * target_rr)
            tp2_base = entry_price - (risk * target_rr * 1.5)
            tp3_base = entry_price - (risk * target_rr * 2.0)
        
        # Adjust TPs based on regime and trend strength
        if regime == "trending" and ((side == "LONG" and mood == "bullish") or (side == "SHORT" and mood == "bearish")):
            # Trending in our direction = extend targets
            tp_mult = 1.2
        elif regime == "sideways" or regime == "choppy":
            # Sideways/choppy = conservative targets
            tp_mult = 0.8
        else:
            tp_mult = 1.0
        
        if side == "LONG":
            tp1 = tp1_base * tp_mult
            tp2 = tp2_base * tp_mult
            tp3 = tp3_base * tp_mult
        else:
            tp1 = tp1_base / tp_mult
            tp2 = tp2_base / tp_mult
            tp3 = tp3_base / tp_mult
        
        # Estimate probabilities from Monte Carlo results
        # Find closest ATR multiples
        tp1_atr_mult = abs(tp1 - entry_price) / atr
        tp2_atr_mult = abs(tp2 - entry_price) / atr
        tp3_atr_mult = abs(tp3 - entry_price) / atr
        
        prob1 = self._interpolate_probability(tp1_atr_mult, target_probabilities)
        prob2 = self._interpolate_probability(tp2_atr_mult, target_probabilities)
        prob3 = self._interpolate_probability(tp3_atr_mult, target_probabilities)
        
        return (tp1, tp2, tp3, [prob1 * 100, prob2 * 100, prob3 * 100])
    
    def _interpolate_probability(
        self,
        atr_mult: float,
        probabilities: Dict[float, float]
    ) -> float:
        """Interpolate probability for a given ATR multiple"""
        sorted_mults = sorted(probabilities.keys())
        
        # Find bracketing values
        lower = max([m for m in sorted_mults if m <= atr_mult], default=sorted_mults[0])
        upper = min([m for m in sorted_mults if m >= atr_mult], default=sorted_mults[-1])
        
        if lower == upper:
            return probabilities[lower]
        
        # Linear interpolation
        lower_prob = probabilities[lower]
        upper_prob = probabilities[upper]
        
        weight = (atr_mult - lower) / (upper - lower)
        return lower_prob + (upper_prob - lower_prob) * weight
    
    def _calculate_expected_value(
        self,
        entry_price: float,
        sl_price: float,
        tp_prices: List[float],
        tp_probabilities: List[float],
        side: str
    ) -> float:
        """
        Calculate expected value (EV) of the trade.
        
        EV = (Prob_TP1 × Profit_TP1) + (Prob_TP2 × Profit_TP2) + ...
             - (Prob_SL × Loss_SL)
        """
        # Simplification: assume equal position size per TP level
        tp_weights = [0.5, 0.3, 0.2]  # 50% at TP1, 30% at TP2, 20% at TP3
        
        total_ev = 0.0
        
        # Calculate profit for each TP
        for i, (tp_price, tp_prob) in enumerate(zip(tp_prices, tp_probabilities)):
            if side == "LONG":
                profit = tp_price - entry_price
            else:
                profit = entry_price - tp_price
            
            # Weight by position size and probability
            weighted_profit = profit * tp_weights[i] * (tp_prob / 100.0)
            total_ev += weighted_profit
        
        # Calculate loss if SL hit (assume remaining position size)
        if side == "LONG":
            loss = entry_price - sl_price
        else:
            loss = sl_price - entry_price
        
        # Probability of hitting SL (conservative estimate)
        # = 1 - max(TP probabilities) to account for partial fills
        prob_sl = 1.0 - max(tp_probabilities) / 100.0
        
        total_ev -= loss * prob_sl
        
        return total_ev
    
    def _get_regime_strategy(self, regime: str, trend_strength: float) -> str:
        """Determine regime-specific exit strategy"""
        if regime == "trending" and trend_strength > 60:
            return "TRAIL_AGGRESSIVE"  # Use trailing stop to ride trend
        elif regime == "trending":
            return "TRAIL_MODERATE"  # Moderate trailing
        elif regime == "choppy":
            return "QUICK_EXIT"  # Take profits quickly in choppy markets
        elif regime == "volatile":
            return "WIDE_STOPS"  # Wide stops, patient exits
        elif regime == "sideways":
            return "RANGE_BOUND"  # Target range extremes
        else:
            return "STANDARD"


# Singleton instance
_manager: Optional[DynamicSLTPManager] = None


def get_dynamic_sltp_manager() -> DynamicSLTPManager:
    """Get singleton manager instance"""
    global _manager
    if _manager is None:
        _manager = DynamicSLTPManager()
    return _manager


def calculate_dynamic_sltp(
    symbol: str,
    side: Literal["LONG", "SHORT"],
    entry_price: float,
    atr: float,
    atr_pct: float,
    market_regime: str,
    market_mood: str,
    trend_strength: float,
    target_rr: float = 1.5,
    volatility_class: str = "medium"
) -> SLTPRecommendation:
    """
    Convenience function for dynamic SL/TP calculation.
    
    Args:
        symbol: Trading symbol
        side: LONG or SHORT
        entry_price: Entry price
        atr: Average True Range (absolute)
        atr_pct: ATR as percentage of price
        market_regime: trending|sideways|choppy|volatile
        market_mood: bullish|bearish|neutral
        trend_strength: 0-100
        target_rr: Target risk/reward ratio
        volatility_class: high|medium|low
        
    Returns:
        SLTPRecommendation with optimal levels
    """
    manager = get_dynamic_sltp_manager()
    return manager.calculate_sltp(
        symbol, side, entry_price, atr, atr_pct,
        market_regime, market_mood, trend_strength,  # type: ignore
        target_rr, volatility_class  # type: ignore
    )
