"""
Dynamic Leverage & Position Sizing Engine (MetaBrain v9.1)
==========================================================
Calculates PRECISE leverage and position size using AI precision calculator.

REMOVED in v9.1:
- ❌ Fixed leverage templates (3x, 5x, 8x, 10x)
- ❌ Percentage ranges (10-20%, 30-40%)
- ❌ IF statements and hardcoded thresholds

ADDED in v9.1:
- ✅ AI Precision Calculator integration
- ✅ Exact leverage decimals (e.g., 7.34x, 4.82x, 9.67x)
- ✅ Exact investment amounts (e.g., $87.23, $973.45)
- ✅ 100% AI-driven decision making

Philosophy: AI decides EXACT numbers based on trade quality, not templates.

Author: AlgoGPT Team
Level: Hedge Fund Grade
"""

import logging
import os
import asyncio
from typing import Dict, Tuple, Optional
from dataclasses import dataclass

LOGGER = logging.getLogger("dynamic_sizing")

# Import AI Precision Calculator (MetaBrain v9.1)
try:
    from utils.precision_calculator import calculate_precision_sizing, get_precision_calculator
    AI_PRECISION_AVAILABLE = True
except ImportError:
    LOGGER.error("❌ AI Precision Calculator UNAVAILABLE - System CANNOT trade without it!")
    AI_PRECISION_AVAILABLE = False
    calculate_precision_sizing = None


@dataclass
class PositionSizing:
    """Position sizing recommendation - MetaBrain v9.1 EXACT values"""
    leverage: float  # EXACT decimal leverage (e.g., 7.34x, 4.82x)
    equity_percent: float  # EXACT equity % (e.g., 23.7%)
    size_usd: float  # EXACT position size in USD
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
        
        # MetaBrain v9.1: Remove hardcoded min/max leverage/equity
        # AI Precision Calculator determines ALL exact values
        # Legacy fallback only if AI unavailable (rare)
        
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
        market_mood: str = "neutral",  # "bullish", "bearish", "neutral"
        symbol: str = "UNKNOWN",  # For AI context
        market_ctx: Optional[Dict] = None  # Full market context for AI
    ) -> PositionSizing:
        """
        Calculate optimal leverage and position size.
        
        MetaBrain v9.1: Uses AI Precision Calculator for EXACT numbers.
        Falls back to legacy logic if AI unavailable.
        
        Returns:
            PositionSizing with PRECISE leverage/investment, not templates
        """
        # MetaBrain v9.1: Try AI Precision Calculator first
        if AI_PRECISION_AVAILABLE and calculate_precision_sizing is not None:
            try:
                self.logger.info(f"{symbol}: Using AI Precision Calculator...")
                
                # Extract volatility percentage from market_ctx
                volatility_pct = 1.5  # Default medium volatility
                if market_ctx:
                    volatility_pct = market_ctx.get("atr_pct", 0.015) * 100  # Convert to %
                
                # Call AI to get EXACT leverage and investment
                precision_result = calculate_precision_sizing(
                    quality_score=quality_score,
                    risk_reward=risk_reward,
                    ai_confidence=ai_confidence,
                    account_balance=account_equity,
                    volatility_pct=volatility_pct,
                    market_regime=market_regime,
                    expected_profit_usd=None,  # Will be calculated later
                    strategy=None  # Can be passed if known
                )
                
                if precision_result:
                    # AI succeeded - use EXACT values
                    self.logger.info(
                        f"{symbol}: AI Precision OK - "
                        f"Leverage={precision_result.leverage:.2f}x (EXACT), "
                        f"Investment=${precision_result.investment_usd:.2f} (EXACT)"
                    )
                    
                    # Convert to PositionSizing format - KEEP EXACT DECIMALS
                    equity_pct = precision_result.investment_pct  # Already calculated
                    
                    result = PositionSizing(
                        leverage=precision_result.leverage,  # EXACT decimal (e.g., 7.34x)
                        equity_percent=equity_pct,
                        size_usd=precision_result.position_size_usd,  # Already calculated
                        confidence_score=precision_result.confidence_score,
                        reasoning=precision_result.reasoning
                    )
                    
                    self.logger.info(
                        f"✅ AI PRECISION: Lev={precision_result.leverage:.2f}x, "
                        f"Invest=${precision_result.investment_usd:.2f}, "
                        f"Pos=${result.size_usd:.2f}"
                    )
                    
                    return result
                else:
                    self.logger.error(f"{symbol}: AI precision returned None - NO FALLBACK!")
                    raise ValueError("AI Precision Calculator required but returned None")
            except Exception as e:
                self.logger.error(f"{symbol}: AI precision failed: {e} - NO FALLBACK!")
                raise
        
        # MetaBrain v9.1: NO fallback allowed! If AI unavailable, system should not trade
        self.logger.error(f"{symbol}: AI Precision Calculator UNAVAILABLE - CANNOT SIZE POSITION!")
        raise RuntimeError(
            "MetaBrain v9.1 requires AI Precision Calculator. "
            "Install precision_calculator module or fix AI integration."
        )


# Global instance
_dynamic_sizing_engine = None

def get_dynamic_sizing_engine() -> DynamicSizingEngine:
    """Get singleton instance"""
    global _dynamic_sizing_engine
    if _dynamic_sizing_engine is None:
        _dynamic_sizing_engine = DynamicSizingEngine()
    return _dynamic_sizing_engine
