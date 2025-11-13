#!/usr/bin/env python3
# utils/dynamic_leverage.py
"""
Hybrid Dynamic Leverage System v2.0
====================================

100% Dynamic leverage (2-35x) with intelligent safety guards.

Features:
- Multi-factor confidence scoring (Quality, Market, Tier, WinRate, ATR)
- 3-Layer safety guards (Emergency, Volatility, Symbol)
- Market regime detection (TRENDING/VOLATILE/CHOPPY/CRASH)
- Portfolio-level protection
- Dynamic blacklist management
- Recovery mode after losses
- Time-based protection
- Real-time performance tracking

Usage:
    calculator = DynamicLeverageCalculator()
    leverage = calculator.calculate_leverage(
        trade_quality=9.0,
        symbol="BTCUSDT",
        atr_pct=0.018,
        current_price=50000
    )
"""

import os
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("algogpt.dynamic_leverage")

# Configuration
DYNAMIC_LEVERAGE_ENABLED = os.getenv("DYNAMIC_LEVERAGE_MODE", "1").lower() in ("1", "true", "yes")
BASE_MIN_LEVERAGE = int(os.getenv("DYNAMIC_MIN_LEVERAGE", "2"))
BASE_MAX_LEVERAGE = int(os.getenv("DYNAMIC_MAX_LEVERAGE", "35"))

# Emergency Brake Settings
EMERGENCY_WIN_RATE_THRESHOLD = float(os.getenv("EMERGENCY_WIN_RATE", "0.30"))
EMERGENCY_CONSECUTIVE_LOSSES = int(os.getenv("EMERGENCY_CONSEC_LOSSES", "3"))
EMERGENCY_DAILY_LOSS_LIMIT = float(os.getenv("EMERGENCY_DAILY_LOSS", "200.0"))

# Volatility Guard
VOLATILITY_EXTREME_ATR = float(os.getenv("VOLATILITY_EXTREME_ATR", "0.05"))  # 5%
VOLATILITY_HIGH_ATR = float(os.getenv("VOLATILITY_HIGH_ATR", "0.03"))  # 3%

# Portfolio Protection
MAX_PORTFOLIO_EXPOSURE = float(os.getenv("MAX_PORTFOLIO_EXPOSURE", "0.30"))  # 30%
MAX_CORRELATED_POSITIONS = int(os.getenv("MAX_CORRELATED_POSITIONS", "2"))

# Recovery Mode
RECOVERY_MODE_LOSS_TRIGGER = float(os.getenv("RECOVERY_LOSS_TRIGGER", "200.0"))
RECOVERY_STEPS = [5, 8, 12, 15, 20, 25, 30]  # Gradual recovery

# Time-based Protection
NIGHT_HOURS_START = int(os.getenv("NIGHT_HOURS_START", "22"))
NIGHT_HOURS_END = int(os.getenv("NIGHT_HOURS_END", "6"))
NIGHT_MAX_LEVERAGE = int(os.getenv("NIGHT_MAX_LEVERAGE", "15"))
WEEKEND_MAX_LEVERAGE = int(os.getenv("WEEKEND_MAX_LEVERAGE", "10"))


class MarketRegime(Enum):
    """Market regime classification"""
    TRENDING = "TRENDING"      # Strong trend, ADX > 30
    VOLATILE = "VOLATILE"      # High volatility, choppy
    CHOPPY = "CHOPPY"         # Low ADX, ranging
    CRASH = "CRASH"           # Extreme volatility, panic


class SymbolTier(Enum):
    """Symbol performance tiers"""
    TIER_A = "A"  # Best performers (win rate > 60%)
    TIER_B = "B"  # Good performers (win rate 45-60%)
    TIER_C = "C"  # Poor performers (win rate 30-45%)
    TIER_D = "D"  # Very poor (win rate < 30%)
    BLACKLIST = "BLACKLIST"  # Banned symbols


@dataclass
class ConfidenceScore:
    """
    Multi-factor confidence score breakdown
    
    Score: 0-10 (higher = more confident)
    Weights: Quality 30%, Market 25%, Tier 20%, WinRate 15%, Volatility 10%
    """
    quality_score: float  # 0-10
    market_score: float   # 0-10
    tier_score: float     # 0-10
    win_rate_score: float # 0-10
    volatility_score: float # 0-10
    
    total_score: float
    breakdown: Dict[str, float]


@dataclass
class SafetyStatus:
    """Safety guards status"""
    emergency_brake_active: bool
    emergency_reason: Optional[str]
    emergency_max_leverage: int
    
    volatility_guard_active: bool
    volatility_reason: Optional[str]
    volatility_max_leverage: int
    
    symbol_protection_active: bool
    symbol_reason: Optional[str]
    symbol_max_leverage: int
    
    time_protection_active: bool
    time_reason: Optional[str]
    time_max_leverage: int
    
    portfolio_protection_active: bool
    portfolio_reason: Optional[str]
    portfolio_max_leverage: int


class DynamicLeverageCalculator:
    """
    Main leverage calculator with multi-layer protection
    
    Calculation flow:
    1. Calculate confidence score (0-10)
    2. Map score to base leverage range
    3. Apply safety guards (Emergency, Volatility, Symbol, Time, Portfolio)
    4. Return final leverage with detailed reasoning
    """
    
    def __init__(self):
        self.enabled = DYNAMIC_LEVERAGE_ENABLED
        self.min_leverage = BASE_MIN_LEVERAGE
        self.max_leverage = BASE_MAX_LEVERAGE
        
        # Performance tracking (simple in-memory for now, will add Redis later)
        self._performance_cache: Dict[str, Dict[str, Any]] = {}
        self._blacklist: Dict[str, datetime] = {}
        self._recovery_mode_active = False
        self._recovery_step = 0
        
        logger.info(
            f"🚀 Dynamic Leverage v2.0 initialized | "
            f"Range: {self.min_leverage}-{self.max_leverage}x | "
            f"Enabled: {self.enabled}"
        )
    
    def calculate_leverage(
        self,
        *,
        trade_quality: float,
        symbol: str,
        atr_pct: float,
        current_price: float,
        adx: Optional[float] = None,
        win_rate: Optional[float] = None,
        market_regime: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Calculate optimal leverage with full reasoning
        
        Args:
            trade_quality: Trade quality score 0-10
            symbol: Trading symbol
            atr_pct: ATR as percentage of price (e.g., 0.025 = 2.5%)
            current_price: Current market price
            adx: ADX indicator value (optional)
            win_rate: Symbol win rate 0-1 (optional)
            market_regime: Override market regime (optional)
            
        Returns:
            {
                "leverage": int (final leverage),
                "confidence_score": ConfidenceScore,
                "safety_status": SafetyStatus,
                "base_leverage_range": (min, max),
                "reasoning": str,
                "guards_applied": List[str]
            }
        """
        if not self.enabled:
            # Fallback to traditional leverage_policy.py
            return {
                "leverage": 10,
                "reasoning": "Dynamic leverage disabled, using default 10x",
                "fallback": True
            }
        
        # Step 1: Calculate confidence score
        confidence = self._calculate_confidence_score(
            trade_quality=trade_quality,
            symbol=symbol,
            atr_pct=atr_pct,
            adx=adx,
            win_rate=win_rate,
            market_regime=market_regime
        )
        
        # Step 2: Map confidence to base leverage range
        base_min, base_max = self._map_confidence_to_leverage(confidence.total_score)
        
        # Step 3: Apply safety guards
        safety = self._apply_safety_guards(
            symbol=symbol,
            atr_pct=atr_pct,
            win_rate=win_rate,
            base_max=base_max,
            **kwargs
        )
        
        # Step 4: Check Recovery Mode
        recovery_max = self.get_recovery_max_leverage()
        if recovery_max is not None:
            base_max = min(base_max, recovery_max)
            logger.info(f"🛡️ Recovery Mode active: Limiting max leverage to {recovery_max}x")
        
        # Step 5: Calculate final leverage
        final_leverage = self._calculate_final_leverage(
            base_min=base_min,
            base_max=base_max,
            safety=safety
        )
        
        # Step 6: Build reasoning
        reasoning, guards_applied = self._build_reasoning(
            confidence=confidence,
            safety=safety,
            base_range=(base_min, base_max),
            final_leverage=final_leverage,
            recovery_mode=self._recovery_mode_active
        )
        
        logger.info(
            f"🎯 {symbol}: Leverage {final_leverage}x | "
            f"Confidence: {confidence.total_score:.1f}/10 | "
            f"Guards: {len(guards_applied)}"
        )
        
        return {
            "leverage": final_leverage,
            "confidence_score": confidence,
            "safety_status": safety,
            "base_leverage_range": (base_min, base_max),
            "reasoning": reasoning,
            "guards_applied": guards_applied
        }
    
    def _calculate_confidence_score(
        self,
        trade_quality: float,
        symbol: str,
        atr_pct: float,
        adx: Optional[float],
        win_rate: Optional[float],
        market_regime: Optional[str]
    ) -> ConfidenceScore:
        """
        Calculate multi-factor confidence score
        
        Weights:
        - Quality: 30%
        - Market: 25%
        - Tier: 20%
        - WinRate: 15%
        - Volatility: 10%
        """
        # 1. Quality score (0-10) - already provided
        quality_score = max(0, min(10, float(trade_quality)))
        
        # 2. Market regime score (0-10)
        if market_regime:
            regime = MarketRegime(market_regime.upper())
        else:
            regime = self._detect_market_regime(atr_pct, adx)
        
        market_score = {
            MarketRegime.TRENDING: 10.0,
            MarketRegime.VOLATILE: 6.0,
            MarketRegime.CHOPPY: 4.0,
            MarketRegime.CRASH: 1.0
        }[regime]
        
        # 3. Symbol tier score (0-10)
        tier = self._get_symbol_tier(symbol, win_rate)
        tier_score = {
            SymbolTier.TIER_A: 10.0,
            SymbolTier.TIER_B: 7.0,
            SymbolTier.TIER_C: 4.0,
            SymbolTier.TIER_D: 2.0,
            SymbolTier.BLACKLIST: 0.0
        }[tier]
        
        # 4. Win rate score (0-10)
        if win_rate is not None:
            win_rate_normalized = max(0, min(1, float(win_rate)))
            win_rate_score = win_rate_normalized * 10
        else:
            # Default to neutral if unknown
            win_rate_score = 5.0
        
        # 5. Volatility score (0-10) - lower volatility = higher score
        if atr_pct < 0.01:  # < 1%
            volatility_score = 10.0
        elif atr_pct < 0.02:  # 1-2%
            volatility_score = 8.0
        elif atr_pct < 0.03:  # 2-3%
            volatility_score = 6.0
        elif atr_pct < 0.05:  # 3-5%
            volatility_score = 4.0
        else:  # > 5%
            volatility_score = 2.0
        
        # Calculate weighted total
        weights = {
            "quality": 0.30,
            "market": 0.25,
            "tier": 0.20,
            "win_rate": 0.15,
            "volatility": 0.10
        }
        
        total_score = (
            quality_score * weights["quality"] +
            market_score * weights["market"] +
            tier_score * weights["tier"] +
            win_rate_score * weights["win_rate"] +
            volatility_score * weights["volatility"]
        )
        
        breakdown = {
            "quality": quality_score,
            "market": market_score,
            "tier": tier_score,
            "win_rate": win_rate_score,
            "volatility": volatility_score,
            "regime": regime.value,
            "symbol_tier": tier.value
        }
        
        return ConfidenceScore(
            quality_score=quality_score,
            market_score=market_score,
            tier_score=tier_score,
            win_rate_score=win_rate_score,
            volatility_score=volatility_score,
            total_score=total_score,
            breakdown=breakdown
        )
    
    def _detect_market_regime(
        self,
        atr_pct: float,
        adx: Optional[float]
    ) -> MarketRegime:
        """
        Detect market regime based on ATR and ADX
        
        TRENDING: ADX > 30
        VOLATILE: ATR > 3%
        CHOPPY: ADX < 20
        CRASH: ATR > 5%
        """
        # CRASH detection (extreme volatility)
        if atr_pct > 0.05:  # > 5%
            return MarketRegime.CRASH
        
        # Use ADX if available
        if adx is not None:
            if adx > 30:
                return MarketRegime.TRENDING
            elif adx < 20:
                return MarketRegime.CHOPPY
        
        # Fallback to ATR-based detection
        if atr_pct > 0.03:  # > 3%
            return MarketRegime.VOLATILE
        elif atr_pct < 0.015:  # < 1.5%
            return MarketRegime.TRENDING
        else:
            return MarketRegime.CHOPPY
    
    def _get_symbol_tier(
        self,
        symbol: str,
        win_rate: Optional[float]
    ) -> SymbolTier:
        """
        Get symbol performance tier
        
        Tier A: Win rate > 60%
        Tier B: Win rate 45-60%
        Tier C: Win rate 30-45%
        Tier D: Win rate < 30%
        Blacklist: Banned
        """
        # Check blacklist
        if symbol in self._blacklist:
            expiry = self._blacklist[symbol]
            if datetime.now(timezone.utc) < expiry:
                return SymbolTier.BLACKLIST
            else:
                # Blacklist expired
                del self._blacklist[symbol]
        
        # Get win rate from cache or parameter
        if win_rate is None:
            perf = self._performance_cache.get(symbol, {})
            win_rate = perf.get("win_rate", 0.5)  # Default to 50% if unknown
        
        # Map to tier
        if win_rate >= 0.60:
            return SymbolTier.TIER_A
        elif win_rate >= 0.45:
            return SymbolTier.TIER_B
        elif win_rate >= 0.30:
            return SymbolTier.TIER_C
        else:
            return SymbolTier.TIER_D
    
    def _map_confidence_to_leverage(
        self,
        confidence_score: float
    ) -> Tuple[int, int]:
        """
        Map confidence score to leverage range
        
        Score 9.0-10.0: 28-35x (TRENDING + Quality 9+ + Tier A)
        Score 8.0-8.9:  20-28x (VOLATILE + Quality 8+ + Tier B)
        Score 7.0-7.9:  15-20x (CHOPPY + Quality 7+ + Tier B)
        Score 6.0-6.9:  10-15x (Quality 6+ + Tier C)
        Score 5.0-5.9:  5-10x  (Quality 5+ + Recovery Mode)
        Score < 5.0:    2-5x   (Low Quality/Recovery)
        """
        if confidence_score >= 9.0:
            return (28, 35)
        elif confidence_score >= 8.0:
            return (20, 28)
        elif confidence_score >= 7.0:
            return (15, 20)
        elif confidence_score >= 6.0:
            return (10, 15)
        elif confidence_score >= 5.0:
            return (5, 10)
        else:
            return (2, 5)
    
    def _apply_safety_guards(
        self,
        symbol: str,
        atr_pct: float,
        win_rate: Optional[float],
        base_max: int,
        **kwargs
    ) -> SafetyStatus:
        """
        Apply all safety guards and return active restrictions
        """
        # Initialize safety status
        safety = SafetyStatus(
            emergency_brake_active=False,
            emergency_reason=None,
            emergency_max_leverage=base_max,
            volatility_guard_active=False,
            volatility_reason=None,
            volatility_max_leverage=base_max,
            symbol_protection_active=False,
            symbol_reason=None,
            symbol_max_leverage=base_max,
            time_protection_active=False,
            time_reason=None,
            time_max_leverage=base_max,
            portfolio_protection_active=False,
            portfolio_reason=None,
            portfolio_max_leverage=base_max
        )
        
        # 1. Emergency Brake
        perf = self._performance_cache.get(symbol, {})
        current_win_rate = win_rate or perf.get("win_rate", 0.5)
        consecutive_losses = perf.get("consecutive_losses", 0)
        daily_loss = perf.get("daily_loss", 0.0)
        
        if current_win_rate < EMERGENCY_WIN_RATE_THRESHOLD:
            safety.emergency_brake_active = True
            safety.emergency_reason = f"Win rate {current_win_rate*100:.0f}% < {EMERGENCY_WIN_RATE_THRESHOLD*100:.0f}%"
            safety.emergency_max_leverage = 5
        
        elif consecutive_losses >= EMERGENCY_CONSECUTIVE_LOSSES:
            safety.emergency_brake_active = True
            safety.emergency_reason = f"{consecutive_losses} consecutive losses"
            safety.emergency_max_leverage = 3
        
        elif daily_loss > EMERGENCY_DAILY_LOSS_LIMIT:
            safety.emergency_brake_active = True
            safety.emergency_reason = f"Daily loss ${daily_loss:.0f} > ${EMERGENCY_DAILY_LOSS_LIMIT:.0f}"
            safety.emergency_max_leverage = 0  # No trading
        
        # 2. Volatility Guard
        if atr_pct > VOLATILITY_EXTREME_ATR:
            safety.volatility_guard_active = True
            safety.volatility_reason = f"Extreme volatility ATR {atr_pct*100:.1f}% > {VOLATILITY_EXTREME_ATR*100:.0f}%"
            safety.volatility_max_leverage = 10
        
        elif atr_pct > VOLATILITY_HIGH_ATR:
            safety.volatility_guard_active = True
            safety.volatility_reason = f"High volatility ATR {atr_pct*100:.1f}% > {VOLATILITY_HIGH_ATR*100:.0f}%"
            safety.volatility_max_leverage = 12
        
        # 3. Symbol Protection
        tier = self._get_symbol_tier(symbol, win_rate)
        if tier == SymbolTier.BLACKLIST:
            safety.symbol_protection_active = True
            safety.symbol_reason = "Symbol blacklisted"
            safety.symbol_max_leverage = 0
        
        elif tier == SymbolTier.TIER_C:
            safety.symbol_protection_active = True
            safety.symbol_reason = "Poor symbol performance (Tier C)"
            safety.symbol_max_leverage = 8
        
        elif tier == SymbolTier.TIER_D:
            safety.symbol_protection_active = True
            safety.symbol_reason = "Very poor symbol performance (Tier D)"
            safety.symbol_max_leverage = 5
        
        # 4. Time-based Protection
        now = datetime.now(timezone.utc)
        hour = now.hour
        is_weekend = now.weekday() >= 5  # Saturday=5, Sunday=6
        
        if NIGHT_HOURS_START <= hour or hour < NIGHT_HOURS_END:
            safety.time_protection_active = True
            safety.time_reason = f"Night hours ({hour}:00 UTC)"
            safety.time_max_leverage = NIGHT_MAX_LEVERAGE
        
        if is_weekend:
            safety.time_protection_active = True
            safety.time_reason = "Weekend trading"
            safety.time_max_leverage = WEEKEND_MAX_LEVERAGE
        
        # 5. Portfolio Protection
        portfolio_exposure = kwargs.get("portfolio_exposure", 0.0)
        correlated_positions = kwargs.get("correlated_positions", 0)
        
        if portfolio_exposure > MAX_PORTFOLIO_EXPOSURE:
            safety.portfolio_protection_active = True
            safety.portfolio_reason = f"Portfolio exposure {portfolio_exposure*100:.0f}% > {MAX_PORTFOLIO_EXPOSURE*100:.0f}%"
            # Reduce leverage by 30%
            safety.portfolio_max_leverage = int(base_max * 0.7)
        
        elif correlated_positions > MAX_CORRELATED_POSITIONS:
            safety.portfolio_protection_active = True
            safety.portfolio_reason = f"{correlated_positions} correlated positions > {MAX_CORRELATED_POSITIONS}"
            # Reduce leverage by 40%
            safety.portfolio_max_leverage = int(base_max * 0.6)
        
        return safety
    
    def _calculate_final_leverage(
        self,
        base_min: int,
        base_max: int,
        safety: SafetyStatus
    ) -> int:
        """
        Calculate final leverage by applying all safety caps
        """
        # Start with base max
        final = base_max
        
        # Apply each safety guard (most restrictive wins)
        if safety.emergency_brake_active:
            final = min(final, safety.emergency_max_leverage)
        
        if safety.volatility_guard_active:
            final = min(final, safety.volatility_max_leverage)
        
        if safety.symbol_protection_active:
            final = min(final, safety.symbol_max_leverage)
        
        if safety.time_protection_active:
            final = min(final, safety.time_max_leverage)
        
        if safety.portfolio_protection_active:
            final = min(final, safety.portfolio_max_leverage)
        
        # Ensure within absolute bounds
        final = max(self.min_leverage, min(self.max_leverage, final))
        
        # Ensure at least base_min (unless guards force lower)
        if not (safety.emergency_brake_active or safety.symbol_protection_active):
            final = max(base_min, final)
        
        return int(final)
    
    def _build_reasoning(
        self,
        confidence: ConfidenceScore,
        safety: SafetyStatus,
        base_range: Tuple[int, int],
        final_leverage: int,
        recovery_mode: bool = False
    ) -> Tuple[str, list]:
        """
        Build detailed reasoning string
        
        Returns:
            (reasoning_text, list_of_active_guards)
        """
        lines = []
        guards = []
        
        # Confidence breakdown
        lines.append(f"Confidence Score: {confidence.total_score:.1f}/10")
        lines.append(f"  Quality: {confidence.quality_score:.1f} (30%)")
        lines.append(f"  Market: {confidence.market_score:.1f} - {confidence.breakdown['regime']} (25%)")
        lines.append(f"  Tier: {confidence.tier_score:.1f} - {confidence.breakdown['symbol_tier']} (20%)")
        lines.append(f"  Win Rate: {confidence.win_rate_score:.1f} (15%)")
        lines.append(f"  Volatility: {confidence.volatility_score:.1f} (10%)")
        
        lines.append(f"\nBase Leverage Range: {base_range[0]}-{base_range[1]}x")
        
        # Recovery mode
        if recovery_mode:
            recovery_max = self.get_recovery_max_leverage()
            lines.append(f"\n🛡️ RECOVERY MODE: Step {self._recovery_step+1}/{len(RECOVERY_STEPS)} → Max {recovery_max}x")
            guards.append("recovery_mode")
        
        # Safety guards
        if safety.emergency_brake_active:
            lines.append(f"\n🚨 EMERGENCY BRAKE: {safety.emergency_reason} → Max {safety.emergency_max_leverage}x")
            guards.append("emergency_brake")
        
        if safety.volatility_guard_active:
            lines.append(f"⚠️  VOLATILITY GUARD: {safety.volatility_reason} → Max {safety.volatility_max_leverage}x")
            guards.append("volatility_guard")
        
        if safety.symbol_protection_active:
            lines.append(f"🛡️  SYMBOL PROTECTION: {safety.symbol_reason} → Max {safety.symbol_max_leverage}x")
            guards.append("symbol_protection")
        
        if safety.time_protection_active:
            lines.append(f"⏰ TIME PROTECTION: {safety.time_reason} → Max {safety.time_max_leverage}x")
            guards.append("time_protection")
        
        if safety.portfolio_protection_active:
            lines.append(f"📊 PORTFOLIO PROTECTION: {safety.portfolio_reason} → Max {safety.portfolio_max_leverage}x")
            guards.append("portfolio_protection")
        
        lines.append(f"\n✅ Final Leverage: {final_leverage}x")
        
        return "\n".join(lines), guards
    
    def update_performance(
        self,
        symbol: str,
        win: bool,
        pnl: float
    ) -> None:
        """
        Update symbol performance tracking
        
        Args:
            symbol: Trading symbol
            win: Whether trade was profitable
            pnl: Profit/loss amount
        """
        if symbol not in self._performance_cache:
            self._performance_cache[symbol] = {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.5,
                "consecutive_losses": 0,
                "consecutive_wins": 0,
                "daily_loss": 0.0,
                "total_pnl": 0.0
            }
        
        perf = self._performance_cache[symbol]
        perf["trades"] += 1
        
        if win:
            perf["wins"] += 1
            perf["consecutive_wins"] += 1
            perf["consecutive_losses"] = 0
        else:
            perf["losses"] += 1
            perf["consecutive_losses"] += 1
            perf["consecutive_wins"] = 0
        
        perf["win_rate"] = perf["wins"] / perf["trades"] if perf["trades"] > 0 else 0.5
        perf["daily_loss"] += abs(pnl) if not win else 0
        perf["total_pnl"] += pnl
        
        # Auto-blacklist check
        if perf["consecutive_losses"] >= EMERGENCY_CONSECUTIVE_LOSSES:
            self._add_to_blacklist(symbol, days=30)
            logger.warning(
                f"🚫 {symbol} auto-blacklisted for 30 days "
                f"({perf['consecutive_losses']} consecutive losses)"
            )
    
    def _add_to_blacklist(
        self,
        symbol: str,
        days: int = 30
    ) -> None:
        """Add symbol to blacklist"""
        expiry = datetime.now(timezone.utc) + timedelta(days=days)
        self._blacklist[symbol] = expiry
    
    def activate_recovery_mode(self, reason: str = "Large losses detected") -> None:
        """
        Activate recovery mode - gradual leverage increase
        
        Recovery steps: 5x → 8x → 12x → 15x → 20x → 25x → 30x
        """
        self._recovery_mode_active = True
        self._recovery_step = 0
        logger.warning(f"🛡️ Recovery Mode ACTIVATED: {reason}")
    
    def advance_recovery_step(self) -> bool:
        """
        Advance recovery step if conditions are met
        
        Returns:
            True if advanced, False if max step reached
        """
        if not self._recovery_mode_active:
            return False
        
        if self._recovery_step < len(RECOVERY_STEPS) - 1:
            self._recovery_step += 1
            current_max = RECOVERY_STEPS[self._recovery_step]
            logger.info(f"📈 Recovery step advanced: Max leverage now {current_max}x")
            return True
        else:
            # Recovery complete
            self._recovery_mode_active = False
            self._recovery_step = 0
            logger.info("✅ Recovery Mode COMPLETED - returning to normal operations")
            return False
    
    def get_recovery_max_leverage(self) -> Optional[int]:
        """Get current recovery mode max leverage"""
        if self._recovery_mode_active:
            return RECOVERY_STEPS[self._recovery_step]
        return None
    
    def calculate_position_size(
        self,
        leverage: int,
        portfolio_value: float,
        confidence_score: float
    ) -> Dict[str, Any]:
        """
        Calculate position size based on leverage
        
        Leverage > 25x: 1% of portfolio
        Leverage > 15x: 2% of portfolio
        Leverage <= 15x: 3-5% of portfolio (based on confidence)
        
        Args:
            leverage: Final leverage value
            portfolio_value: Total portfolio value
            confidence_score: Confidence score 0-10
            
        Returns:
            {
                "size_pct": float (position size as % of portfolio),
                "size_usd": float (position size in USD),
                "reasoning": str
            }
        """
        if leverage > 25:
            size_pct = 0.01  # 1%
            reasoning = "High leverage (>25x) → Conservative 1% position"
        elif leverage > 15:
            size_pct = 0.02  # 2%
            reasoning = "Medium leverage (15-25x) → Moderate 2% position"
        else:
            # Scale by confidence: 3-5%
            base_pct = 0.03
            confidence_bonus = (confidence_score / 10.0) * 0.02  # Up to +2%
            size_pct = base_pct + confidence_bonus
            reasoning = f"Low leverage (≤15x) + Confidence {confidence_score:.1f}/10 → {size_pct*100:.1f}% position"
        
        size_usd = portfolio_value * size_pct
        
        return {
            "size_pct": size_pct,
            "size_usd": size_usd,
            "reasoning": reasoning
        }
    
    def get_leverage_stats(self) -> Dict[str, Any]:
        """Get system statistics"""
        return {
            "enabled": self.enabled,
            "leverage_range": f"{self.min_leverage}-{self.max_leverage}x",
            "tracked_symbols": len(self._performance_cache),
            "blacklisted_symbols": len(self._blacklist),
            "recovery_mode": self._recovery_mode_active,
            "recovery_step": self._recovery_step,
            "recovery_max_leverage": self.get_recovery_max_leverage()
        }


# Singleton instance
_calculator: Optional[DynamicLeverageCalculator] = None


def get_dynamic_leverage_calculator() -> DynamicLeverageCalculator:
    """Get or create singleton calculator"""
    global _calculator
    if _calculator is None:
        _calculator = DynamicLeverageCalculator()
    return _calculator


# Convenience function
def calculate_dynamic_leverage(
    trade_quality: float,
    symbol: str,
    atr_pct: float,
    current_price: float,
    **kwargs
) -> int:
    """
    Quick leverage calculation
    
    Returns just the leverage value (int)
    """
    calc = get_dynamic_leverage_calculator()
    result = calc.calculate_leverage(
        trade_quality=trade_quality,
        symbol=symbol,
        atr_pct=atr_pct,
        current_price=current_price,
        **kwargs
    )
    return result["leverage"]


# Public API
__all__ = [
    "DynamicLeverageCalculator",
    "get_dynamic_leverage_calculator",
    "calculate_dynamic_leverage",
    "MarketRegime",
    "SymbolTier",
    "ConfidenceScore",
    "SafetyStatus"
]
