#!/usr/bin/env python3
"""
Precision Leverage & Investment Calculator - 100% Dynamic, Zero Templates
=========================================================================
AI calculates EXACT leverage (7.34x, 4.82x, 9.67x) and EXACT investment
amount ($87.23, $973.45) based on trade quality, market conditions, and
wallet state. NO hardcoded templates like 3x/5x/8x or 10%/30%/50%.

Replaces static logic:
  ❌ if confidence >= 90: leverage = 10x
  ❌ if score 9-10: invest 50-60%
  
With dynamic precision:
  ✅ AI calculates: leverage = 7.34x, investment = $487.23
  ✅ Every trade gets unique sizing
  ✅ Complete transparency with reasoning

Part of MetaBrain v9.1 - Market Breathing System
"""

import logging
import math
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("algogpt.precision_calculator")


@dataclass
class PrecisionSizing:
    """Precision position sizing result"""
    leverage: float  # Exact leverage (e.g., 7.34x)
    investment_usd: float  # Exact USD to invest (e.g., $487.23)
    investment_pct: float  # % of wallet (informational)
    position_size_usd: float  # Total position after leverage
    confidence_score: float  # 0-100 overall confidence
    reasoning: str  # Why these exact numbers


class PrecisionCalculator:
    """
    Calculates exact leverage and investment amounts dynamically.
    
    Unlike template-based systems that use ranges (3x/5x/8x or 10%/30%/50%),
    this system calculates PRECISE values for each individual trade based on:
    
    - Trade Quality Score (0-10)
    - Risk/Reward Ratio
    - AI Confidence (0-100)
    - Market Regime (CHOPPY/TRENDING/VOLATILE)
    - Volatility Level
    - Account Balance
    - Recent Performance
    
    Output examples:
    - Weak trade: 3.47x leverage, $87.23 investment
    - Medium trade: 5.89x leverage, $312.45 investment
    - Strong trade: 8.12x leverage, $973.67 investment
    """
    
    def __init__(self):
        self.logger = logger
        
        # Hard limits (for safety only, NOT templates)
        self.MIN_LEVERAGE = 1.0
        self.MAX_LEVERAGE = 35.0  # Dynamic range 1-35x (aligned with DynamicLeverageCalculator)
        self.MIN_INVESTMENT_USD = 25.0  # Minimum position size ($25 × 5x leverage = $125 notional, meets Binance $100 min)
        self.MIN_WALLET_PCT = 1.0  # At least 1% of wallet
        self.MAX_WALLET_PCT = 95.0  # Leave 5% buffer
    
    def calculate_precision(
        self,
        quality_score: float,  # 0-10 from technical analysis
        risk_reward: float,  # RR ratio (e.g., 1.5, 2.0, 3.5)
        ai_confidence: float,  # 0-100 from AI consensus
        market_regime: str,  # CHOPPY/TRENDING/VOLATILE/SIDEWAYS
        volatility_pct: float,  # Current ATR% or volatility
        account_balance: float,  # Available USD in wallet
        expected_profit_usd: Optional[float] = None,  # Expected profit from TP
        strategy: Optional[str] = None  # GRID/Mean-Reversion/Scalping
    ) -> PrecisionSizing:
        """
        Calculate precision leverage and investment amount.
        
        Returns exact values tailored to this specific trade.
        """
        self.logger.info(
            f"🧮 Precision Calculator: Q={quality_score:.1f}, RR={risk_reward:.2f}, "
            f"AI={ai_confidence:.0f}%, Regime={market_regime}, Vol={volatility_pct:.2f}%"
        )
        
        # Step 1: Calculate base confidence (0-1.0)
        base_confidence = self._calculate_base_confidence(
            quality_score, risk_reward, ai_confidence
        )
        
        # Step 2: Adjust for market conditions
        market_multiplier = self._get_market_multiplier(
            market_regime, volatility_pct, strategy
        )
        
        adjusted_confidence = base_confidence * market_multiplier
        adjusted_confidence = max(0.0, min(1.0, adjusted_confidence))
        
        # Step 3: Calculate EXACT leverage (not template)
        leverage = self._calculate_exact_leverage(
            adjusted_confidence,
            volatility_pct,
            risk_reward,
            market_regime
        )
        
        # Step 4: Calculate EXACT investment amount
        investment_usd = self._calculate_exact_investment(
            adjusted_confidence,
            account_balance,
            quality_score,
            risk_reward,
            expected_profit_usd
        )
        
        # Step 5: Calculate position size
        position_size_usd = investment_usd * leverage
        investment_pct = (investment_usd / account_balance * 100.0) if account_balance > 0 else 0
        
        # Step 6: Generate reasoning
        reasoning = self._generate_reasoning(
            quality_score, risk_reward, ai_confidence,
            leverage, investment_usd, investment_pct,
            market_regime, volatility_pct, strategy
        )
        
        result = PrecisionSizing(
            leverage=leverage,
            investment_usd=investment_usd,
            investment_pct=investment_pct,
            position_size_usd=position_size_usd,
            confidence_score=adjusted_confidence * 100.0,
            reasoning=reasoning
        )
        
        self.logger.info(
            f"💰 Precision Result: Leverage={leverage:.2f}x, "
            f"Investment=${investment_usd:.2f} ({investment_pct:.1f}%), "
            f"Position=${position_size_usd:.2f}"
        )
        
        return result
    
    def _calculate_base_confidence(
        self,
        quality: float,
        rr: float,
        ai_conf: float
    ) -> float:
        """
        Calculate base confidence (0-1.0) from inputs.
        
        Weights:
        - Quality: 40%
        - Risk/Reward: 30%
        - AI Confidence: 30%
        """
        # Normalize quality (0-10) to 0-1
        quality_norm = quality / 10.0
        
        # Normalize RR (1.0-4.0 typical) to 0-1
        # RR 1.0 = 0, RR 2.0 = 0.33, RR 3.0 = 0.67, RR 4.0+ = 1.0
        rr_norm = min(1.0, (rr - 1.0) / 3.0)
        
        # AI confidence already 0-100, normalize to 0-1
        ai_norm = ai_conf / 100.0
        
        # Weighted average
        confidence = (
            quality_norm * 0.40 +
            rr_norm * 0.30 +
            ai_norm * 0.30
        )
        
        return confidence
    
    def _get_market_multiplier(
        self,
        regime: str,
        volatility_pct: float,
        strategy: Optional[str]
    ) -> float:
        """
        Calculate market condition multiplier (0.5 - 1.3).
        
        Adjusts confidence based on how favorable current market is.
        """
        multiplier = 1.0
        
        # Regime adjustments
        regime_upper = regime.upper()
        if regime_upper == "TRENDING":
            multiplier *= 1.15  # Trending = easier to trade
        elif regime_upper == "CHOPPY":
            multiplier *= 0.85  # Choppy = harder
        elif regime_upper == "VOLATILE":
            multiplier *= 0.75  # Volatile = risky
        elif regime_upper == "SIDEWAYS":
            multiplier *= 0.95  # Sideways = moderate
        
        # Volatility adjustments (fine-grained)
        if volatility_pct > 3.0:
            multiplier *= 0.80  # Very high volatility = reduce
        elif volatility_pct > 2.0:
            multiplier *= 0.90  # High volatility
        elif volatility_pct < 0.5:
            multiplier *= 1.10  # Low volatility = safer
        
        # Strategy-specific boosts
        if strategy:
            strategy_upper = strategy.upper()
            if strategy_upper == "GRID" and regime_upper in ("CHOPPY", "SIDEWAYS"):
                multiplier *= 1.05  # GRID excels in range-bound
            elif strategy_upper == "MEAN_REVERSION" and volatility_pct < 1.5:
                multiplier *= 1.08  # Mean-reversion better in low vol
        
        return multiplier
    
    def _calculate_exact_leverage(
        self,
        confidence: float,  # 0-1.0
        volatility_pct: float,
        rr: float,
        regime: str
    ) -> float:
        """
        Calculate EXACT leverage as continuous function (not template).
        
        Formula: leverage = base_leverage * volatility_adj * regime_adj
        
        Returns precision values like: 3.47x, 7.89x, 9.12x
        """
        # Base leverage from confidence (continuous curve)
        # confidence=0 → 2.0x, confidence=0.5 → 5.5x, confidence=1.0 → 9.5x
        base_leverage = 2.0 + (confidence ** 1.2) * 7.5
        
        # Volatility adjustment (reduce leverage in high vol)
        if volatility_pct > 2.5:
            vol_adj = 0.75
        elif volatility_pct > 1.5:
            vol_adj = 0.85
        elif volatility_pct > 1.0:
            vol_adj = 0.95
        else:
            vol_adj = 1.0
        
        base_leverage *= vol_adj
        
        # Risk/Reward boost (better RR = can use more leverage)
        if rr >= 3.0:
            base_leverage *= 1.10
        elif rr >= 2.5:
            base_leverage *= 1.05
        
        # Regime fine-tuning
        if regime.upper() == "VOLATILE":
            base_leverage *= 0.85  # Extra conservative in volatile
        
        # Clamp to limits
        leverage = max(self.MIN_LEVERAGE, min(self.MAX_LEVERAGE, base_leverage))
        
        # Round to 2 decimal places for precision
        return round(leverage, 2)
    
    def _calculate_exact_investment(
        self,
        confidence: float,  # 0-1.0
        balance: float,
        quality: float,
        rr: float,
        expected_profit: Optional[float]
    ) -> float:
        """
        Calculate EXACT investment amount in USD (not template percentage).
        
        Philosophy:
        - High confidence + good trade → invest more
        - Low confidence → invest less
        - But NEVER use fixed % buckets
        
        Returns precision values like: $87.23, $487.65, $973.12
        """
        import os
        
        # Base percentage from confidence (continuous curve)
        # confidence=0 → 5%, confidence=0.5 → 35%, confidence=1.0 → 90%
        base_pct = 5.0 + (confidence ** 1.3) * 85.0
        
        # Quality adjustment (fine-grained)
        if quality >= 8.5:
            base_pct *= 1.12
        elif quality >= 7.5:
            base_pct *= 1.06
        elif quality <= 4.0:
            base_pct *= 0.75
        
        # Risk/Reward adjustment
        if rr >= 3.0:
            base_pct *= 1.08
        elif rr >= 2.5:
            base_pct *= 1.04
        elif rr < 1.5:
            base_pct *= 0.85
        
        # Expected profit consideration
        if expected_profit and expected_profit > 0:
            # If expected profit is HIGH relative to balance, can invest more
            profit_ratio = expected_profit / balance if balance > 0 else 0
            if profit_ratio > 0.05:  # 5%+ expected return
                base_pct *= 1.10
            elif profit_ratio > 0.03:  # 3%+ expected return
                base_pct *= 1.05
        
        # Clamp to limits
        base_pct = max(self.MIN_WALLET_PCT, min(self.MAX_WALLET_PCT, base_pct))
        
        # Calculate exact USD amount
        investment = (balance * base_pct / 100.0)
        
        # Ensure minimum - use ENV override to bypass singleton cache
        min_investment_override = float(os.getenv("MIN_INVESTMENT_USD", "25.0"))
        investment = max(min_investment_override, investment)
        
        # Round to 2 decimals
        return round(investment, 2)
    
    def _generate_reasoning(
        self,
        quality: float,
        rr: float,
        ai_conf: float,
        leverage: float,
        investment: float,
        investment_pct: float,
        regime: str,
        volatility: float,
        strategy: Optional[str]
    ) -> str:
        """Generate human-readable reasoning in Hebrew + English"""
        
        # Quality label
        if quality >= 8.5:
            q_label = "exceptional"
        elif quality >= 7.0:
            q_label = "excellent"
        elif quality >= 5.5:
            q_label = "good"
        else:
            q_label = "acceptable"
        
        # RR label
        if rr >= 3.0:
            rr_label = "יצוין"
        elif rr >= 2.0:
            rr_label = "טוב"
        else:
            rr_label = "סביר"
        
        # Investment reasoning
        if investment_pct > 70:
            inv_reason = "השקעה גדולה - setup חזק מאוד, confidence גבוהה"
        elif investment_pct > 40:
            inv_reason = "השקעה בינונית-גבוהה - setup טוב עם potential"
        elif investment_pct > 20:
            inv_reason = "השקעה בינונית - setup סביר, risk managed"
        else:
            inv_reason = "השקעה קטנה - setup חלש או תנאי שוק לא אידיאליים"
        
        # Leverage reasoning
        if leverage >= 8.0:
            lev_reason = f"מינוף גבוה ({leverage:.2f}x) - confidence גבוהה + volatility נמוכה"
        elif leverage >= 5.0:
            lev_reason = f"מינוף בינוני ({leverage:.2f}x) - איזון בין capital efficiency לסיכון"
        else:
            lev_reason = f"מינוף נמוך ({leverage:.2f}x) - conservative approach בשל תנאים"
        
        reasoning = (
            f"{q_label.capitalize()} setup (Q={quality:.1f}, RR={rr:.2f} {rr_label}, AI={ai_conf:.0f}%) "
            f"ב-{regime} market (Vol={volatility:.2f}%). "
            f"{inv_reason}. {lev_reason}."
        )
        
        return reasoning


# Singleton instance
_precision_calculator: Optional[PrecisionCalculator] = None


def get_precision_calculator() -> PrecisionCalculator:
    """Get or create singleton precision calculator"""
    global _precision_calculator
    if _precision_calculator is None:
        _precision_calculator = PrecisionCalculator()
    return _precision_calculator


def calculate_precision_sizing(
    quality_score: float,
    risk_reward: float,
    ai_confidence: float,
    market_regime: str,
    volatility_pct: float,
    account_balance: float,
    expected_profit_usd: Optional[float] = None,
    strategy: Optional[str] = None
) -> PrecisionSizing:
    """
    Convenience function for precision sizing calculation.
    
    Returns exact leverage and investment amounts (no templates).
    """
    calc = get_precision_calculator()
    return calc.calculate_precision(
        quality_score=quality_score,
        risk_reward=risk_reward,
        ai_confidence=ai_confidence,
        market_regime=market_regime,
        volatility_pct=volatility_pct,
        account_balance=account_balance,
        expected_profit_usd=expected_profit_usd,
        strategy=strategy
    )
