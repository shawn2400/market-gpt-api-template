"""
Dynamic Leverage & Position Sizing Engine
==========================================
Calculates optimal leverage and position size based on trade quality.

Philosophy:
- High-quality trades (quality 9/10, RR 2.5, AI 85%) → Higher leverage (8-10x) + Larger size (50-60%)
- Medium trades (quality 6/10, RR 1.5, AI 65%) → Medium leverage (4-6x) + Medium size (25-35%)
- Low trades (quality 4/10, RR 1.3, AI 50%) → Low leverage (2-3x) + Small size (10-20%)

This maximizes capital efficiency while managing risk intelligently.

Author: AlgoGPT Team
Level: Hedge Fund Grade
"""

import logging
import os
from typing import Dict, Tuple
from dataclasses import dataclass

LOGGER = logging.getLogger("dynamic_sizing")


@dataclass
class PositionSizing:
    """Position sizing recommendation"""
    leverage: int  # 1-10x
    equity_percent: float  # 10-60% of account equity
    size_usd: float  # Actual position size in USD
    confidence_score: float  # 0-100 overall confidence
    reasoning: str  # Why these values were chosen


class DynamicSizingEngine:
    """
    Calculates optimal leverage and position size dynamically.
    
    Inputs:
    - Quality Score (0-10): From technical analysis
    - Risk/Reward Ratio: Entry vs TP1/SL
    - AI Confidence: Predicted success %
    - Volatility: Market volatility level
    - Account Equity: Total available capital
    
    Outputs:
    - Leverage (1-10x): Higher for better trades
    - Position Size (% of equity): Higher for better trades
    - Size in USD: Actual amount to invest
    """
    
    def __init__(self):
        self.logger = LOGGER
        
        # Configuration
        self.min_leverage = int(os.getenv("MIN_LEVERAGE", "2"))
        self.max_leverage = int(os.getenv("MAX_LEVERAGE", "10"))
        self.min_equity_pct = float(os.getenv("MIN_EQUITY_PCT", "10"))  # 10%
        self.max_equity_pct = float(os.getenv("MAX_EQUITY_PCT", "60"))  # 60%
        
        # Risk multipliers
        self.conservative_mode = os.getenv("CONSERVATIVE_SIZING", "0") == "1"
    
    def calculate_position(
        self,
        quality_score: float,  # 0-10
        risk_reward: float,  # RR ratio
        ai_confidence: float,  # 0-100
        volatility: str,  # "high", "medium", "low"
        account_equity: float,  # Total equity in USD
        market_regime: str = "unknown",  # "trending", "sideways", "choppy"
        market_mood: str = "neutral"  # "bullish", "bearish", "neutral"
    ) -> PositionSizing:
        """
        Calculate optimal leverage and position size.
        
        Returns:
            PositionSizing with leverage, equity_percent, size_usd, and reasoning
        """
        # 1. Calculate base confidence score (0-100)
        base_confidence = self._calculate_base_confidence(
            quality_score, risk_reward, ai_confidence
        )
        
        # 2. Adjust for market conditions
        adjusted_confidence = self._adjust_for_market_conditions(
            base_confidence, volatility, market_regime, market_mood
        )
        
        # 3. Calculate leverage (1-10x)
        leverage = self._calculate_leverage(adjusted_confidence, volatility)
        
        # 4. Calculate equity percentage (10-60%)
        equity_pct = self._calculate_equity_percent(
            adjusted_confidence, volatility, risk_reward
        )
        
        # 5. Calculate actual size in USD
        size_usd = (account_equity * equity_pct / 100.0) * leverage
        
        # 6. Generate reasoning
        reasoning = self._generate_reasoning(
            quality_score, risk_reward, ai_confidence,
            leverage, equity_pct, volatility, market_regime
        )
        
        result = PositionSizing(
            leverage=leverage,
            equity_percent=equity_pct,
            size_usd=size_usd,
            confidence_score=adjusted_confidence,
            reasoning=reasoning
        )
        
        self.logger.info(
            f"📊 Position Sizing: Leverage={leverage}x, "
            f"Equity={equity_pct:.1f}%, Size=${size_usd:.2f}, "
            f"Confidence={adjusted_confidence:.1f}"
        )
        
        return result
    
    def _calculate_base_confidence(
        self,
        quality: float,
        rr: float,
        ai_conf: float
    ) -> float:
        """
        Calculate base confidence from quality, RR, and AI prediction.
        
        Weights:
        - Quality Score: 40%
        - Risk/Reward: 30%
        - AI Confidence: 30%
        """
        # Normalize quality (0-10) to 0-100
        quality_normalized = (quality / 10.0) * 100.0
        
        # Normalize RR (1.0-3.0) to 0-100
        # RR 1.0 = 0, RR 2.0 = 50, RR 3.0 = 100
        rr_normalized = min(100.0, ((rr - 1.0) / 2.0) * 100.0)
        
        # AI confidence already 0-100
        
        # Weighted average
        confidence = (
            quality_normalized * 0.40 +
            rr_normalized * 0.30 +
            ai_conf * 0.30
        )
        
        return max(0.0, min(100.0, confidence))
    
    def _adjust_for_market_conditions(
        self,
        base_confidence: float,
        volatility: str,
        regime: str,
        mood: str
    ) -> float:
        """Adjust confidence based on market conditions"""
        adjusted = base_confidence
        
        # Volatility adjustments
        if volatility == "high":
            adjusted *= 0.85  # Reduce confidence in high volatility
        elif volatility == "low":
            adjusted *= 1.05  # Slight boost in low volatility
        
        # Regime adjustments
        if regime == "trending":
            adjusted *= 1.10  # Trending markets easier to trade
        elif regime == "choppy":
            adjusted *= 0.80  # Choppy markets harder
        elif regime == "volatile":
            adjusted *= 0.75  # Very uncertain
        
        # Mood adjustments
        if mood in ["bullish", "bearish"]:
            adjusted *= 1.05  # Clear direction helps
        else:
            adjusted *= 0.95  # Neutral = less certain
        
        return max(0.0, min(100.0, adjusted))
    
    def _calculate_leverage(
        self,
        confidence: float,
        volatility: str
    ) -> int:
        """
        Calculate leverage (1-10x) based on confidence.
        
        Confidence → Leverage mapping:
        90-100: 9-10x (exceptional trades)
        80-90:  7-8x (excellent trades)
        70-80:  5-6x (good trades)
        60-70:  4-5x (decent trades)
        50-60:  3-4x (acceptable trades)
        <50:    2-3x (marginal trades)
        """
        # Base leverage from confidence
        if confidence >= 90:
            base_lev = 10
        elif confidence >= 80:
            base_lev = 8
        elif confidence >= 70:
            base_lev = 6
        elif confidence >= 60:
            base_lev = 5
        elif confidence >= 50:
            base_lev = 4
        else:
            base_lev = 3
        
        # Reduce leverage in high volatility
        if volatility == "high":
            base_lev = max(self.min_leverage, int(base_lev * 0.7))
        
        # Conservative mode
        if self.conservative_mode:
            base_lev = max(self.min_leverage, int(base_lev * 0.8))
        
        # Clamp to min/max
        return max(self.min_leverage, min(self.max_leverage, base_lev))
    
    def _calculate_equity_percent(
        self,
        confidence: float,
        volatility: str,
        rr: float
    ) -> float:
        """
        Calculate what % of equity to risk.
        
        Confidence → Equity % mapping:
        90-100: 50-60% (go big on exceptional setups)
        80-90:  40-50% (large positions)
        70-80:  30-40% (good positions)
        60-70:  25-35% (medium positions)
        50-60:  15-25% (small positions)
        <50:    10-15% (minimal positions)
        """
        # Base equity % from confidence
        if confidence >= 90:
            base_pct = 55.0
        elif confidence >= 80:
            base_pct = 45.0
        elif confidence >= 70:
            base_pct = 35.0
        elif confidence >= 60:
            base_pct = 30.0
        elif confidence >= 50:
            base_pct = 20.0
        else:
            base_pct = 12.0
        
        # Adjust for RR (better RR = can risk more)
        if rr >= 2.5:
            base_pct *= 1.15
        elif rr >= 2.0:
            base_pct *= 1.10
        elif rr < 1.5:
            base_pct *= 0.85
        
        # Reduce in high volatility
        if volatility == "high":
            base_pct *= 0.80
        elif volatility == "low":
            base_pct *= 1.05
        
        # Conservative mode
        if self.conservative_mode:
            base_pct *= 0.75
        
        # Clamp to min/max
        return max(self.min_equity_pct, min(self.max_equity_pct, base_pct))
    
    def _generate_reasoning(
        self,
        quality: float,
        rr: float,
        ai_conf: float,
        leverage: int,
        equity_pct: float,
        volatility: str,
        regime: str
    ) -> str:
        """Generate human-readable reasoning"""
        
        quality_label = "exceptional" if quality >= 8.5 else "excellent" if quality >= 7 else "good" if quality >= 5.5 else "acceptable"
        rr_label = "excellent" if rr >= 2.5 else "great" if rr >= 2.0 else "good" if rr >= 1.5 else "acceptable"
        
        return (
            f"{quality_label.capitalize()} setup (Q={quality:.1f}/10, RR={rr:.2f}, AI={ai_conf:.0f}%) "
            f"in {regime} {volatility}-vol market → "
            f"{leverage}x leverage, {equity_pct:.1f}% equity"
        )


# Global instance
_dynamic_sizing_engine = None

def get_dynamic_sizing_engine() -> DynamicSizingEngine:
    """Get singleton instance"""
    global _dynamic_sizing_engine
    if _dynamic_sizing_engine is None:
        _dynamic_sizing_engine = DynamicSizingEngine()
    return _dynamic_sizing_engine
