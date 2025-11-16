# -*- coding: utf-8 -*-
# utils/position_scorer.py
"""
Position Score Calculator - Multi-Factor Quality Scoring System
Calculates comprehensive position score (0-10) based on multiple factors
"""
import logging
from typing import Dict, Optional, Any

logger = logging.getLogger("algogpt.position_scorer")

class PositionScorer:
    """
    Advanced position scoring system that evaluates trade quality based on:
    - Market regime alignment
    - Volatility quality
    - Technical strength (RSI, MACD, ADX)
    - Volume/liquidity
    - Risk/Reward ratio
    - BTC correlation (for altcoins)
    """
    
    def __init__(self):
        self.regime_weights = {
            "TRENDING": {"breakout": 1.2, "trend_following": 1.3, "mean_reversion": 0.7},
            "CHOPPY": {"grid": 1.3, "mean_reversion": 1.2, "breakout": 0.8},
            "VOLATILE": {"scalping": 1.1, "mean_reversion": 0.9, "grid": 0.8},
            "SIDEWAYS": {"mean_reversion": 1.3, "grid": 1.2, "trend_following": 0.7}
        }
    
    def calculate_position_score(
        self,
        symbol: str,
        strategy: str,
        context: Dict[str, Any],
        risk_reward: float = 2.0
    ) -> float:
        """
        Calculate comprehensive position score (0-10)
        
        Args:
            symbol: Trading symbol
            strategy: Trading strategy (grid, mean_reversion, breakout, etc.)
            context: Market context with indicators
            risk_reward: Risk/reward ratio
            
        Returns:
            Position score 0-10
        """
        try:
            # Extract market data from context
            regime = context.get("regime", "CHOPPY")
            mood = context.get("mood", "NEUTRAL")
            volatility = context.get("volatility", "medium")
            
            # Get technical indicators
            adx = context.get("adx", 20.0)
            rsi = context.get("rsi", 50.0)
            atr_pct = context.get("atr_percent", 2.5)
            volume_24h = context.get("volume_24h", 0.0)
            
            # 1. Regime Alignment Score (25%)
            regime_score = self._score_regime_alignment(strategy, regime, mood)
            
            # 2. Volatility Quality Score (20%)
            volatility_score = self._score_volatility_quality(atr_pct, strategy, volatility)
            
            # 3. Technical Strength Score (25%)
            technical_score = self._score_technical_strength(adx, rsi, strategy)
            
            # 4. Liquidity/Volume Score (15%)
            liquidity_score = self._score_liquidity(symbol, volume_24h)
            
            # 5. Risk/Reward Quality Score (15%)
            rr_score = self._score_risk_reward(risk_reward, strategy)
            
            # Calculate weighted total
            position_score = (
                regime_score * 0.25 +
                volatility_score * 0.20 +
                technical_score * 0.25 +
                liquidity_score * 0.15 +
                rr_score * 0.15
            )
            
            # Clamp to 0-10 range
            final_score = max(0.0, min(10.0, position_score))
            
            logger.debug(
                f"Position Score for {symbol}: {final_score:.1f}/10 "
                f"(regime={regime_score:.1f}, vol={volatility_score:.1f}, "
                f"tech={technical_score:.1f}, liq={liquidity_score:.1f}, rr={rr_score:.1f})"
            )
            
            return round(final_score, 1)
            
        except Exception as e:
            logger.error(f"Failed to calculate position score for {symbol}: {e}")
            return 5.0  # Neutral fallback
    
    def _score_regime_alignment(self, strategy: str, regime: str, mood: str) -> float:
        """Score how well strategy aligns with market regime (0-10)"""
        # Get base weight for strategy-regime combo
        weights = self.regime_weights.get(regime, {})
        base_multiplier = weights.get(strategy, 1.0)
        
        # Base score starts at 5.0 (neutral)
        base_score = 5.0
        
        # Apply regime multiplier
        regime_score = base_score * base_multiplier
        
        # Mood adjustment
        if mood == "BULLISH" and strategy in ["breakout", "trend_following", "dip"]:
            regime_score *= 1.15
        elif mood == "BEARISH" and strategy in ["mean_reversion", "grid"]:
            regime_score *= 1.10
        elif mood == "NEUTRAL" and strategy in ["grid", "mean_reversion"]:
            regime_score *= 1.05
        
        return min(10.0, regime_score)
    
    def _score_volatility_quality(self, atr_pct: float, strategy: str, volatility: str) -> float:
        """Score volatility quality for the strategy (0-10)"""
        # Optimal volatility ranges by strategy
        optimal_ranges = {
            "grid": (0.5, 3.0),  # Low-medium volatility
            "mean_reversion": (1.0, 4.0),  # Medium volatility
            "breakout": (2.0, 5.0),  # Medium-high volatility
            "scalping": (0.5, 2.0),  # Low volatility
            "trend_following": (1.5, 4.0)  # Medium volatility
        }
        
        optimal_min, optimal_max = optimal_ranges.get(strategy, (1.0, 4.0))
        
        # Score based on distance from optimal range
        if optimal_min <= atr_pct <= optimal_max:
            # Perfect range
            score = 10.0
        elif atr_pct < optimal_min:
            # Too low - scale down
            distance = (optimal_min - atr_pct) / optimal_min
            score = max(3.0, 10.0 * (1 - distance))
        else:
            # Too high - scale down more aggressively
            distance = (atr_pct - optimal_max) / optimal_max
            score = max(2.0, 10.0 * (1 - distance * 1.5))
        
        return score
    
    def _score_technical_strength(self, adx: float, rsi: float, strategy: str) -> float:
        """Score technical indicators strength (0-10)"""
        # ADX component (trend strength)
        if strategy in ["trend_following", "breakout"]:
            # High ADX is good
            if adx >= 30:
                adx_score = 10.0
            elif adx >= 20:
                adx_score = 7.0
            elif adx >= 15:
                adx_score = 5.0
            else:
                adx_score = 3.0
        else:
            # Low ADX is good for mean-reversion/grid
            if adx < 15:
                adx_score = 10.0
            elif adx < 20:
                adx_score = 8.0
            elif adx < 25:
                adx_score = 6.0
            elif adx < 30:
                adx_score = 4.0
            else:
                adx_score = 2.0
        
        # RSI component (momentum quality)
        if strategy == "mean_reversion":
            # Extreme RSI is good (reversal opportunity)
            if rsi <= 30 or rsi >= 70:
                rsi_score = 10.0
            elif rsi <= 35 or rsi >= 65:
                rsi_score = 7.0
            elif rsi <= 40 or rsi >= 60:
                rsi_score = 5.0
            else:
                rsi_score = 3.0
        else:
            # Moderate RSI is good (sustainable momentum)
            if 40 <= rsi <= 60:
                rsi_score = 10.0
            elif 35 <= rsi <= 65:
                rsi_score = 7.0
            elif 30 <= rsi <= 70:
                rsi_score = 5.0
            else:
                rsi_score = 3.0
        
        # Weighted average (60% ADX, 40% RSI)
        return adx_score * 0.6 + rsi_score * 0.4
    
    def _score_liquidity(self, symbol: str, volume_24h: float) -> float:
        """Score liquidity/volume quality (0-10)"""
        # Volume thresholds (in millions)
        if volume_24h >= 500_000_000:  # $500M+
            return 10.0
        elif volume_24h >= 200_000_000:  # $200M+
            return 8.5
        elif volume_24h >= 100_000_000:  # $100M+
            return 7.5
        elif volume_24h >= 50_000_000:  # $50M+
            return 6.5
        elif volume_24h >= 20_000_000:  # $20M+
            return 5.5
        elif volume_24h >= 10_000_000:  # $10M+
            return 4.5
        else:
            return 3.0  # Low liquidity warning
    
    def _score_risk_reward(self, rr_ratio: float, strategy: str) -> float:
        """Score risk/reward ratio quality (0-10)"""
        # Optimal RR ratios by strategy
        optimal_rr = {
            "grid": 1.5,
            "mean_reversion": 2.5,
            "breakout": 2.0,
            "scalping": 1.2,
            "trend_following": 2.5
        }
        
        target_rr = optimal_rr.get(strategy, 2.0)
        
        # Score based on how close to optimal
        if rr_ratio >= target_rr * 1.2:
            return 10.0  # Excellent RR
        elif rr_ratio >= target_rr:
            return 8.5  # Good RR
        elif rr_ratio >= target_rr * 0.8:
            return 7.0  # Acceptable RR
        elif rr_ratio >= target_rr * 0.6:
            return 5.0  # Suboptimal RR
        else:
            return 3.0  # Poor RR


# Singleton instance
_position_scorer_instance = None

def get_position_scorer() -> PositionScorer:
    """Get singleton PositionScorer instance"""
    global _position_scorer_instance
    if _position_scorer_instance is None:
        _position_scorer_instance = PositionScorer()
    return _position_scorer_instance
