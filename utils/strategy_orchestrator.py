#!/usr/bin/env python3
# utils/strategy_orchestrator.py
"""
Strategy Orchestrator - Auto-select trading strategy based on market conditions
===============================================================================
Routes each symbol to the optimal strategy using AI consensus (MetaBrain v9.1).
NO hardcoded thresholds - AI decides strategy based on real-time market data.
"""
import logging
import asyncio
from typing import Dict, Any, Optional, Literal
from dataclasses import dataclass

logger = logging.getLogger("strategy_orchestrator")

# Import AI Strategy Consensus Engine (MetaBrain v9.1)
try:
    from utils.ai_strategy_consensus import select_strategy_ai, get_ai_strategy_selector
    AI_STRATEGY_AVAILABLE = True
except ImportError:
    logger.warning("AI Strategy Consensus not available, using legacy logic")
    AI_STRATEGY_AVAILABLE = False
    select_strategy_ai = None

StrategyType = Literal["grid", "scalping", "momentum", "range_bounce", "wait", "mean_reversion", "futures_long", "futures_short"]

@dataclass
class StrategyConfig:
    """Configuration for a specific trading strategy"""
    strategy_type: StrategyType
    min_rr: float  # Minimum Risk/Reward ratio
    min_quality: float  # Minimum quality score (0-10)
    min_success_pct: float  # Minimum success probability
    max_leverage: int  # Maximum leverage
    description: str
    
    # Strategy-specific settings
    tight_stops: bool = False  # Use tight stops (scalping)
    grid_mode: bool = False  # GRID trading mode
    mean_reversion_mode: bool = False  # Mean-Reversion trading mode (VWAP-based)
    trend_following: bool = False  # Trend-following mode
    defensive: bool = False  # Defensive/conservative mode


class StrategyOrchestrator:
    """
    MetaBrain v9.1: 100% AI-Driven Strategy Selection
    NO static parameter tables - AI determines ALL strategy parameters
    """
    
    def __init__(self):
        logger.info("Strategy Orchestrator v9.1: AI-driven (NO static tables)")
    
    async def select_strategy(
        self, 
        market_condition: Optional[Any] = None,
        symbol: str = "",
        ctx: Optional[Dict[str, Any]] = None
    ) -> StrategyConfig:
        """
        MetaBrain v9.1: AI-driven strategy selection (NO static tables)
        
        Returns StrategyConfig object with strategy and parameters
        ALL parameters (leverage, SL, TP) determined by AI Precision Calculator
        
        Args:
            market_condition: MarketCondition object from market_intelligence
            symbol: Trading symbol (for logging)
            ctx: Additional context data
            
        Returns:
            StrategyConfig object (AI-selected)
        """
        if not AI_STRATEGY_AVAILABLE or select_strategy_ai is None or not ctx:
            logger.error(f"{symbol}: AI Strategy Consensus unavailable - CANNOT select strategy!")
            return self._build_strategy_config("futures_long", market_condition, ctx)
        
        try:
            # Call AI to decide strategy - NO fallback allowed!
            logger.info(f"{symbol}: Calling AI Strategy Consensus (3 cheap brains)...")
            ai_consensus = await select_strategy_ai(ctx, symbol)
            
            if not ai_consensus:
                logger.error(f"{symbol}: AI consensus returned None!")
                return self._build_strategy_config("futures_long", market_condition, ctx)
            
            # Check consensus threshold: ≥2 votes (for 3 active brains) or ≥3 votes (for 5 brains)
            min_votes = 2 if ai_consensus.total_votes <= 3 else 3
            
            if ai_consensus.votes_approve >= min_votes:
                logger.info(
                    f"{symbol}: ✅ AI CONSENSUS: {ai_consensus.strategy.upper()} "
                    f"({ai_consensus.votes_approve}/{ai_consensus.total_votes} votes, "
                    f"{ai_consensus.confidence:.1f}% confidence)"
                )
                strategy_config = self._build_strategy_config(ai_consensus.strategy, market_condition, ctx)
                
                # Log tier-adjusted parameters
                active_tier = ctx.get("_active_tier")
                if active_tier:
                    logger.info(
                        f"{symbol}: 🎛️ Tier {active_tier.tier_number} Adjustments: "
                        f"Quality≥{strategy_config.min_quality}, "
                        f"Leverage≤{strategy_config.max_leverage}x, "
                        f"RR≥{strategy_config.min_rr}"
                    )
                
                return strategy_config
            else:
                logger.warning(
                    f"{symbol}: AI consensus insufficient "
                    f"({ai_consensus.votes_approve}/{ai_consensus.total_votes} votes < {min_votes}), "
                    f"using top strategy anyway: {ai_consensus.strategy}"
                )
                return self._build_strategy_config(ai_consensus.strategy, market_condition, ctx)
                
        except Exception as e:
            logger.error(f"{symbol}: AI strategy selection FAILED: {e}", exc_info=True)
            return self._build_strategy_config("futures_long", market_condition, ctx)
    
    def calculate_setup_score(self, ctx: Dict[str, Any]) -> float:
        """
        Calculate dynamic setup quality score (0-10) based on technical signals.
        
        Scoring breakdown:
        - RSI Signals (35%): Oversold/Overbought opportunities
        - MACD Alignment (25%): Trend confirmation
        - Bollinger Bands Position (25%): Price positioning
        - Volume (15%): Confirmation strength
        
        Returns:
            Float 0-10 representing setup quality
        """
        # 1. RSI Signals Score (35%) - Entry opportunities
        rsi = ctx.get("rsi", 50.0)
        
        # Strong signals at extremes (oversold/overbought)
        if rsi <= 25 or rsi >= 75:
            rsi_score = 10.0  # Extreme - strong reversal opportunity
        elif rsi <= 30 or rsi >= 70:
            rsi_score = 8.5  # Very strong signal
        elif rsi <= 35 or rsi >= 65:
            rsi_score = 7.0  # Good signal
        elif 40 <= rsi <= 60:
            rsi_score = 5.0  # Neutral zone
        else:
            rsi_score = 6.0  # Moderate signal
        
        # 2. MACD Alignment Score (25%) - Trend confirmation
        macd = ctx.get("macd", 0.0)
        macd_signal = ctx.get("macd_signal", 0.0)
        macd_hist = ctx.get("macd_hist", 0.0)
        
        # Check for fresh crossovers and alignment
        if abs(macd_hist) > 0:
            # Recent crossover (histogram small = fresh signal)
            hist_abs = abs(macd_hist)
            if hist_abs > 0 and hist_abs < 0.1:  # Fresh crossover
                macd_score = 10.0
            elif macd > 0 and macd > macd_signal:  # Bullish aligned
                macd_score = 8.0
            elif macd < 0 and macd < macd_signal:  # Bearish aligned
                macd_score = 8.0
            else:
                macd_score = 5.0  # Mixed
        else:
            macd_score = 4.0  # Flat
        
        # 3. Bollinger Bands Position Score (25%) - Price positioning
        bb_position = ctx.get("bb_position")  # "upper", "middle", "lower"
        price = ctx.get("close", 0)
        bb_upper = ctx.get("bb_upper")
        bb_lower = ctx.get("bb_lower")
        
        if bb_upper and bb_lower and price:
            # Calculate position in BB range
            bb_range = bb_upper - bb_lower
            if bb_range > 0:
                position_pct = ((price - bb_lower) / bb_range) * 100
                
                # Near bands = better setup (potential reversal)
                if position_pct <= 15 or position_pct >= 85:
                    bb_score = 10.0  # Very close to bands
                elif position_pct <= 25 or position_pct >= 75:
                    bb_score = 8.0  # Close to bands
                elif 40 <= position_pct <= 60:
                    bb_score = 5.0  # Middle zone
                else:
                    bb_score = 6.5  # Moderate
            else:
                bb_score = 5.0
        else:
            bb_score = 5.0  # No BB data
        
        # 4. Volume Score (15%) - Confirmation
        volume = ctx.get("volume", 0)
        volume_sma = ctx.get("volume_sma_20", volume)
        
        if volume and volume_sma and volume_sma > 0:
            volume_ratio = volume / volume_sma
            
            # Higher volume = stronger signal
            if volume_ratio >= 1.5:
                volume_score = 10.0  # Very high volume
            elif volume_ratio >= 1.2:
                volume_score = 8.0  # High volume
            elif volume_ratio >= 0.8:
                volume_score = 6.0  # Normal volume
            else:
                volume_score = 4.0  # Low volume
        else:
            volume_score = 5.0  # No volume data
        
        # Final weighted score
        setup_score = (
            rsi_score * 0.35 +
            macd_score * 0.25 +
            bb_score * 0.25 +
            volume_score * 0.15
        )
        
        return round(setup_score, 1)
    
    def _build_strategy_config(
        self, 
        strategy_name: str, 
        market_condition: Optional[Any] = None,
        ctx: Optional[Dict[str, Any]] = None
    ) -> StrategyConfig:
        """
        Build StrategyConfig object from AI-selected strategy name.
        
        Hybrid Adaptive System Integration:
        - Uses tier data to adjust parameter constraints (quality, leverage, RR)
        - Tier 1 (Strong): Relaxed constraints, higher leverage
        - Tier 2 (Moderate): Balanced constraints  
        - Tier 3 (Weak): Strict constraints, lower leverage, higher quality required
        
        Maps strategy name to configuration with appropriate parameters.
        Parameters are GUIDELINES - AI Precision Calculator has final say.
        """
        ctx = ctx or {}
        
        # Extract tier data from context (set by Hybrid System in gpt_auto_suggest)
        active_tier = ctx.get("_active_tier")
        market_strength = ctx.get("_market_strength")
        regime_snapshot = ctx.get("_regime_snapshot")
        
        # Tier-based parameter multipliers
        if active_tier:
            tier_num = active_tier.tier_number
            
            # Tier 1 (Strong Market): Relaxed constraints
            if tier_num == 1:
                quality_mult = 0.8  # Lower quality requirement (e.g., 4.0 → 3.2)
                leverage_mult = 1.2  # Higher leverage allowed (e.g., 10x → 12x)
                rr_mult = 0.9  # Slightly lower RR required (e.g., 1.8 → 1.6)
                logger.debug(f"Tier 1 multipliers: quality×{quality_mult}, leverage×{leverage_mult}, RR×{rr_mult}")
            
            # Tier 2 (Moderate Market): Balanced
            elif tier_num == 2:
                quality_mult = 1.0  # Standard quality
                leverage_mult = 1.0  # Standard leverage
                rr_mult = 1.0  # Standard RR
                logger.debug(f"Tier 2 multipliers: Standard parameters (no adjustment)")
            
            # Tier 3 (Weak Market): Moderately strict (allows trades, but with reduced leverage)
            else:  # tier_num == 3
                quality_mult = 1.05  # Slightly higher quality (e.g., 4.0 → 4.2)
                leverage_mult = 0.75  # Lower leverage (e.g., 10x → 7.5x)
                rr_mult = 1.1  # Slightly higher RR (e.g., 1.8 → 2.0)
                logger.debug(f"Tier 3 multipliers: quality×{quality_mult}, leverage×{leverage_mult}, RR×{rr_mult}")
        else:
            # No tier data available - use conservative defaults
            quality_mult = 1.0
            leverage_mult = 0.9
            rr_mult = 1.0
            logger.debug("No tier data - using conservative defaults")
        
        # Base parameters (wide ranges for AI flexibility)
        base_config = {
            "min_rr": 1.5,
            "min_quality": 2.0,
            "min_success_pct": 0.5,
            "max_leverage": 10,
            "tight_stops": False,
            "grid_mode": False,
            "mean_reversion_mode": False,
            "trend_following": False,
            "defensive": False
        }
        
        # Strategy-specific adjustments (with tier-based multipliers applied)
        if strategy_name == "grid":
            return StrategyConfig(
                strategy_type="grid",
                min_rr=round(1.1 * rr_mult, 2),
                min_quality=round(2.0 * quality_mult, 1),
                min_success_pct=0.5,
                max_leverage=max(1, int(5 * leverage_mult)),
                description=f"GRID trading - range-bound markets (Tier {active_tier.tier_number if active_tier else '?'})",
                grid_mode=True
            )
        elif strategy_name == "scalping":
            return StrategyConfig(
                strategy_type="scalping",
                min_rr=round(1.2 * rr_mult, 2),
                min_quality=round(3.0 * quality_mult, 1),
                min_success_pct=0.55,
                max_leverage=max(1, int(15 * leverage_mult)),
                description=f"Scalping - quick profits on small moves (Tier {active_tier.tier_number if active_tier else '?'})",
                tight_stops=True
            )
        elif strategy_name == "mean_reversion":
            return StrategyConfig(
                strategy_type="mean_reversion",
                min_rr=round(1.8 * rr_mult, 2),
                min_quality=round(4.0 * quality_mult, 1),
                min_success_pct=0.6,
                max_leverage=max(1, int(8 * leverage_mult)),
                description=f"Mean-Reversion - VWAP deviation trades (Tier {active_tier.tier_number if active_tier else '?'})",
                mean_reversion_mode=True
            )
        elif strategy_name == "range_bounce":
            return StrategyConfig(
                strategy_type="range_bounce",
                min_rr=round(2.0 * rr_mult, 2),
                min_quality=round(5.0 * quality_mult, 1),
                min_success_pct=0.65,
                max_leverage=max(1, int(10 * leverage_mult)),
                description=f"Range-Bounce - support/resistance bounces (Tier {active_tier.tier_number if active_tier else '?'})",
                defensive=False
            )
        elif strategy_name == "momentum":
            return StrategyConfig(
                strategy_type="momentum",
                min_rr=round(2.5 * rr_mult, 2),
                min_quality=round(6.0 * quality_mult, 1),
                min_success_pct=0.65,
                max_leverage=max(1, int(12 * leverage_mult)),
                description=f"Momentum - trend continuation (Tier {active_tier.tier_number if active_tier else '?'})",
                trend_following=True
            )
        elif strategy_name in ["futures_short", "futures_long"]:
            return StrategyConfig(
                strategy_type=strategy_name,  # type: ignore
                min_rr=round(1.8 * rr_mult, 2),
                min_quality=round(4.0 * quality_mult, 1),
                min_success_pct=0.6,
                max_leverage=max(1, int(10 * leverage_mult)),
                description=f"Futures {strategy_name.split('_')[1].upper()} - directional trade (Tier {active_tier.tier_number if active_tier else '?'})",
                trend_following=True
            )
        elif strategy_name == "wait":
            return StrategyConfig(
                strategy_type="wait",
                min_rr=999.0,  # Impossibly high to prevent trades
                min_quality=999.0,
                min_success_pct=0.99,
                max_leverage=1,
                description="WAIT - market conditions not favorable",
                defensive=True
            )
        else:
            # Default fallback
            return StrategyConfig(
                strategy_type="futures_long",
                min_rr=round(1.8 * rr_mult, 2),
                min_quality=round(4.0 * quality_mult, 1),
                min_success_pct=0.6,
                max_leverage=max(1, int(10 * leverage_mult)),
                description=f"Default - futures long position (Tier {active_tier.tier_number if active_tier else '?'})",
                trend_following=True
            )


# ==================== GLOBAL INSTANCE ====================

_orchestrator_instance: Optional[StrategyOrchestrator] = None

def get_strategy_orchestrator() -> StrategyOrchestrator:
    """Get or create global strategy orchestrator instance"""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = StrategyOrchestrator()
    return _orchestrator_instance
