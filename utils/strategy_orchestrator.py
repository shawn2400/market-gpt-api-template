#!/usr/bin/env python3
# utils/strategy_orchestrator.py
"""
Strategy Orchestrator - Auto-select trading strategy based on market conditions
===============================================================================
Routes each symbol to the optimal strategy: GRID, Scalping, Momentum, Range-Bounce, or WAIT
"""
import logging
from typing import Dict, Any, Optional, Literal
from dataclasses import dataclass

logger = logging.getLogger("strategy_orchestrator")

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
    Central orchestrator that selects optimal trading strategy based on market conditions
    """
    
    def __init__(self):
        self.strategies = self._init_strategies()
        logger.info("Strategy Orchestrator initialized with 7 strategies")
    
    def _init_strategies(self) -> Dict[str, StrategyConfig]:
        """Initialize all available trading strategies with their parameters"""
        return {
            # ==================== CHOPPY MARKETS ====================
            "grid_choppy": StrategyConfig(
                strategy_type="grid",
                min_rr=1.10,  # Lower RR for grid (many small wins)
                min_quality=4.0,  # Lower quality threshold
                min_success_pct=60.0,  # Grid has high win rate
                max_leverage=5,  # Conservative leverage
                description="GRID Trading - Range-bound choppy markets (2%+ range)",
                grid_mode=True
            ),
            
            "scalping_choppy": StrategyConfig(
                strategy_type="scalping",
                min_rr=1.10,  # Very tight RR for scalping
                min_quality=4.5,  # Medium-low quality OK
                min_success_pct=65.0,  # Scalping needs high win rate
                max_leverage=8,  # Medium leverage
                description="Scalping - Quick in/out trades in choppy markets",
                tight_stops=True
            ),
            
            "mean_reversion_choppy": StrategyConfig(
                strategy_type="mean_reversion",
                min_rr=1.05,  # Lower RR acceptable (high win rate 70%+)
                min_quality=5.0,  # Medium quality
                min_success_pct=70.0,  # High win rate expected
                max_leverage=6,  # Conservative leverage
                description="Mean-Reversion - VWAP deviation trades in low-range choppy markets (<2% range)",
                tight_stops=True,
                mean_reversion_mode=True
            ),
            
            # ==================== SIDEWAYS MARKETS ====================
            "range_bounce": StrategyConfig(
                strategy_type="range_bounce",
                min_rr=1.15,  # Slightly higher RR
                min_quality=5.0,  # Medium quality
                min_success_pct=60.0,  # Good win rate
                max_leverage=10,  # Standard leverage
                description="Range Bounce - Support/Resistance bounces in sideways markets"
            ),
            
            "grid_sideways": StrategyConfig(
                strategy_type="grid",
                min_rr=1.15,  # Slightly higher than choppy
                min_quality=5.0,  # Medium quality
                min_success_pct=65.0,  # Higher win rate expected
                max_leverage=5,  # Conservative
                description="GRID Trading - Wider ranges in sideways markets",
                grid_mode=True
            ),
            
            # ==================== TRENDING MARKETS ====================
            "momentum_trending": StrategyConfig(
                strategy_type="momentum",
                min_rr=1.25,  # Higher RR for trending
                min_quality=6.0,  # Higher quality required
                min_success_pct=55.0,  # Lower win rate but bigger wins
                max_leverage=15,  # Higher leverage allowed
                description="Momentum - Trend-following in strong trending markets",
                trend_following=True
            ),
            
            # ==================== VOLATILE MARKETS ====================
            "breakout_volatile": StrategyConfig(
                strategy_type="momentum",
                min_rr=1.40,  # Much higher RR for volatility
                min_quality=6.5,  # High quality required
                min_success_pct=50.0,  # Lower win rate acceptable
                max_leverage=10,  # Reduced leverage for safety
                description="Breakout - Capture explosive moves in volatile markets",
                defensive=True
            ),
            
            # ==================== UNCERTAIN / WAIT ====================
            "wait_defensive": StrategyConfig(
                strategy_type="wait",
                min_rr=2.00,  # Very high RR required
                min_quality=8.0,  # Extremely high quality
                min_success_pct=75.0,  # Very high confidence
                max_leverage=5,  # Very conservative
                description="WAIT Mode - Only perfect setups in uncertain conditions",
                defensive=True
            ),
        }
    
    def select_strategy(
        self, 
        market_condition: Optional[Any] = None,
        symbol: str = "",
        ctx: Optional[Dict[str, Any]] = None
    ) -> StrategyConfig:
        """
        Select optimal trading strategy based on market conditions
        
        Args:
            market_condition: MarketCondition object from market_intelligence
            symbol: Trading symbol (for logging)
            ctx: Additional context data
            
        Returns:
            StrategyConfig with optimal parameters
        """
        # Default fallback
        default_strategy = "range_bounce"
        
        if market_condition is None:
            logger.warning(f"{symbol}: No market condition provided, using default {default_strategy}")
            return self.strategies[default_strategy]
        
        # Extract market regime and mood
        regime = getattr(market_condition, 'regime', 'UNKNOWN').upper()
        mood = getattr(market_condition, 'mood', 'NEUTRAL').upper()
        recommended_strategy = getattr(market_condition, 'recommended_strategy', 'futures_long')
        
        logger.info(f"{symbol}: Market={regime}/{mood}, Recommended={recommended_strategy}")
        
        # ==================== DECISION TREE ====================
        
        # 1. CHOPPY Markets → GRID, Mean-Reversion, or Scalping
        if regime == "CHOPPY":
            # Check if GRID is viable (need sufficient range ≥2%)
            if ctx and self._is_grid_viable(ctx):
                strategy_key = "grid_choppy"
                logger.info(f"{symbol}: CHOPPY → GRID Trading (range ≥2%)")
            # Check if Mean-Reversion is viable (range <2%, low volatility)
            elif ctx and self._is_mean_reversion_viable(ctx):
                strategy_key = "mean_reversion_choppy"
                logger.info(f"{symbol}: CHOPPY → Mean-Reversion (range <2%, deterministic VWAP)")
            else:
                strategy_key = "scalping_choppy"
                logger.info(f"{symbol}: CHOPPY → Scalping (fallback)")
        
        # 2. SIDEWAYS Markets → Range Bounce or GRID
        elif regime == "SIDEWAYS":
            # Prefer GRID if range is wide enough
            if ctx and self._is_grid_viable(ctx):
                strategy_key = "grid_sideways"
                logger.info(f"{symbol}: SIDEWAYS → GRID Trading")
            else:
                strategy_key = "range_bounce"
                logger.info(f"{symbol}: SIDEWAYS → Range Bounce")
        
        # 3. TRENDING Markets → Momentum
        elif regime == "TRENDING":
            strategy_key = "momentum_trending"
            logger.info(f"{symbol}: TRENDING → Momentum/Trend-Following")
        
        # 4. VOLATILE Markets → Breakout (with caution)
        elif regime == "VOLATILE":
            strategy_key = "breakout_volatile"
            logger.info(f"{symbol}: VOLATILE → Breakout (high RR required)")
        
        # 5. UNKNOWN or NEUTRAL → Wait for clarity (but allow good setups)
        else:
            # Check mood for hints
            if mood in ("BULLISH", "BEARISH") and regime != "UNKNOWN":
                strategy_key = "range_bounce"  # Moderate approach
                logger.info(f"{symbol}: {regime}/{mood} → Range Bounce (moderate)")
            else:
                strategy_key = "wait_defensive"
                logger.info(f"{symbol}: UNKNOWN/NEUTRAL → WAIT (defensive mode)")
        
        selected = self.strategies[strategy_key]
        logger.info(
            f"{symbol}: Selected [{strategy_key}] - "
            f"MinRR={selected.min_rr:.2f}, MinQuality={selected.min_quality:.1f}, "
            f"MaxLev={selected.max_leverage}x"
        )
        
        return selected
    
    def _is_grid_viable(self, ctx: Dict[str, Any]) -> bool:
        """
        Check if GRID trading is viable based on current range
        
        Args:
            ctx: Market context with price/range data
            
        Returns:
            True if GRID is viable (range ≥ 2%)
        """
        try:
            # Check if we have range data
            filters = ctx.get("filters", {})
            
            # Option 1: Explicit range_pct from filters
            range_pct = filters.get("range_pct")
            if range_pct and float(range_pct) >= 2.0:
                return True
            
            # Option 2: Calculate from high/low
            high_24h = ctx.get("high_24h") or filters.get("high_24h")
            low_24h = ctx.get("low_24h") or filters.get("low_24h")
            
            if high_24h and low_24h:
                high_24h = float(high_24h)
                low_24h = float(low_24h)
                if low_24h > 0:
                    range_pct = ((high_24h - low_24h) / low_24h) * 100.0
                    return range_pct >= 2.0
            
            # Option 3: Check ATR% (volatility proxy)
            atr_pct = ctx.get("atr_pct") or filters.get("atr_pct")
            if atr_pct and float(atr_pct) >= 1.5:  # High ATR suggests range
                return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Grid viability check failed: {e}")
            return False
    
    def _is_mean_reversion_viable(self, ctx: Dict[str, Any]) -> bool:
        """
        Check if Mean-Reversion strategy is viable
        
        Args:
            ctx: Market context with price/range data
            
        Returns:
            True if Mean-Reversion is viable (range <2%, low volatility)
        """
        try:
            filters = ctx.get("filters", {})
            
            # Calculate range percentage
            range_pct = filters.get("range_pct")
            if range_pct is None:
                high_24h = ctx.get("high_24h") or filters.get("high_24h")
                low_24h = ctx.get("low_24h") or filters.get("low_24h")
                
                if high_24h and low_24h:
                    high_24h = float(high_24h)
                    low_24h = float(low_24h)
                    if low_24h > 0:
                        range_pct = ((high_24h - low_24h) / low_24h) * 100.0
            
            # If range_pct is available and ≥2%, GRID is better - skip mean-reversion
            if range_pct is not None and float(range_pct) >= 2.0:
                return False
            
            # Check volatility - avoid only VERY high volatility
            volatility = filters.get("volatility", "").lower()
            if volatility == "extreme":  # Only block extreme volatility
                return False
            
            # ATR check - prefer low to mid volatility (but allow up to 5% for more opportunities)
            atr_pct = ctx.get("atr_pct") or filters.get("atr_pct")
            if atr_pct and float(atr_pct) > 5.0:  # Very high volatility
                return False
            
            # If range <2% OR range unknown in CHOPPY market → Mean-Reversion viable
            return True
            
        except Exception as e:
            logger.debug(f"Mean-reversion viability check failed: {e}")
            return False
    
    def get_strategy_stats(self) -> Dict[str, Any]:
        """Get statistics about available strategies"""
        return {
            "total_strategies": len(self.strategies),
            "strategies": {
                name: {
                    "type": cfg.strategy_type,
                    "min_rr": cfg.min_rr,
                    "description": cfg.description
                }
                for name, cfg in self.strategies.items()
            }
        }


# ==================== GLOBAL INSTANCE ====================

_orchestrator_instance: Optional[StrategyOrchestrator] = None

def get_strategy_orchestrator() -> StrategyOrchestrator:
    """Get or create global strategy orchestrator instance"""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = StrategyOrchestrator()
    return _orchestrator_instance
