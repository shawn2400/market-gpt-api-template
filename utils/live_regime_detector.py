#!/usr/bin/env python3
"""
Live Regime Detector - Real-Time Market Regime Detection
========================================================
Detects market regime changes in REAL-TIME and triggers immediate
strategy adaptation. No waiting for next scan cycle.

Monitors:
- CHOPPY → TRENDING transitions
- TRENDING → VOLATILE transitions  
- VOLATILE → CHOPPY transitions
- SIDEWAYS ↔ Any regime

When regime changes, system immediately:
1. Re-evaluates current positions
2. Adjusts strategy selection
3. Updates SL/TP parameters
4. Notifies via Telegram

Part of MetaBrain v9.1 - Market Breathing System
"""

import logging
import time
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("algogpt.live_regime_detector")


class MarketRegime(str, Enum):
    """Market regime types"""
    CHOPPY = "CHOPPY"
    TRENDING = "TRENDING"
    VOLATILE = "VOLATILE"
    SIDEWAYS = "SIDEWAYS"
    UNKNOWN = "UNKNOWN"


@dataclass
class RegimeChange:
    """Market regime change event"""
    symbol: str
    old_regime: MarketRegime
    new_regime: MarketRegime
    confidence: float  # 0-100
    timestamp: float
    indicators: Dict[str, Any]  # Supporting data
    action_required: str  # What to do now


class LiveRegimeDetector:
    """
    Detects market regime changes in real-time.
    
    Uses:
    - ADX (trend strength)
    - ATR% (volatility)
    - Bollinger Band width
    - Price range analysis
    - EMA alignment
    
    Triggers callbacks when regime changes detected.
    """
    
    def __init__(self):
        self.logger = logger
        self.current_regimes: Dict[str, MarketRegime] = {}  # symbol → regime
        self.last_check: Dict[str, float] = {}  # symbol → timestamp
        self.regime_callbacks: list[Callable] = []  # Callbacks on change
        
        # Regime detection thresholds
        self.ADX_TRENDING = 25.0  # ADX > 25 = trending
        self.ATR_VOLATILE = 2.5  # ATR% > 2.5% = volatile
        self.RANGE_CHOPPY = 2.0  # Range < 2% = choppy
    
    def detect_regime(
        self,
        symbol: str,
        market_ctx: Dict[str, Any],
        force_check: bool = False
    ) -> MarketRegime:
        """
        Detect current market regime.
        
        Args:
            symbol: Trading symbol
            market_ctx: Market indicators
            force_check: Force detection even if checked recently
        
        Returns:
            Current MarketRegime
        """
        # Check if we need to re-detect
        now = time.time()
        last_check = self.last_check.get(symbol, 0)
        
        if not force_check and (now - last_check) < 60:  # Cache for 60s
            return self.current_regimes.get(symbol, MarketRegime.UNKNOWN)
        
        # Extract indicators
        adx = market_ctx.get("adx", 20.0)
        atr_pct = market_ctx.get("atr_pct", 0) * 100  # Convert to %
        
        # Calculate price range
        high_24h = market_ctx.get("high_24h", 0)
        low_24h = market_ctx.get("low_24h", 0)
        close = market_ctx.get("close", 0)
        
        range_pct = 0.0
        if low_24h and low_24h > 0:
            range_pct = ((high_24h - low_24h) / low_24h) * 100.0
        
        # Bollinger Band width
        bb_upper = market_ctx.get("bb_upper")
        bb_lower = market_ctx.get("bb_lower")
        bb_width_pct = 0.0
        if bb_upper and bb_lower and close > 0:
            bb_width_pct = ((bb_upper - bb_lower) / close) * 100.0
        
        # Detect regime
        new_regime = self._classify_regime(
            adx, atr_pct, range_pct, bb_width_pct
        )
        
        # Check if regime changed
        old_regime = self.current_regimes.get(symbol, MarketRegime.UNKNOWN)
        
        if new_regime != old_regime and old_regime != MarketRegime.UNKNOWN:
            # Regime changed!
            self._handle_regime_change(
                symbol, old_regime, new_regime,
                {"adx": adx, "atr_pct": atr_pct, "range_pct": range_pct}
            )
        
        # Update state
        self.current_regimes[symbol] = new_regime
        self.last_check[symbol] = now
        
        return new_regime
    
    def _classify_regime(
        self,
        adx: float,
        atr_pct: float,
        range_pct: float,
        bb_width: float
    ) -> MarketRegime:
        """
        Classify market regime based on indicators.
        
        Logic:
        - VOLATILE: High ATR% (>2.5%) OR wide BB (>4%)
        - TRENDING: High ADX (>25) AND moderate ATR
        - CHOPPY: Low range (<2%) AND low ADX
        - SIDEWAYS: Moderate range, moderate ADX
        """
        # VOLATILE detection (priority)
        if atr_pct > self.ATR_VOLATILE or bb_width > 4.0:
            return MarketRegime.VOLATILE
        
        # TRENDING detection
        if adx > self.ADX_TRENDING and range_pct >= 1.5:
            return MarketRegime.TRENDING
        
        # CHOPPY detection
        if range_pct < self.RANGE_CHOPPY and adx < 20:
            return MarketRegime.CHOPPY
        
        # SIDEWAYS (default)
        return MarketRegime.SIDEWAYS
    
    def _handle_regime_change(
        self,
        symbol: str,
        old_regime: MarketRegime,
        new_regime: MarketRegime,
        indicators: Dict[str, Any]
    ) -> None:
        """Handle regime change event"""
        
        self.logger.warning(
            f"🌊 REGIME CHANGE DETECTED: {symbol} "
            f"{old_regime.value} → {new_regime.value} | "
            f"ADX={indicators.get('adx', 0):.1f}, "
            f"ATR={indicators.get('atr_pct', 0):.2f}%"
        )
        
        # Determine action required
        action = self._get_regime_action(old_regime, new_regime)
        
        # Create change event
        change = RegimeChange(
            symbol=symbol,
            old_regime=old_regime,
            new_regime=new_regime,
            confidence=80.0,  # High confidence for clear transitions
            timestamp=time.time(),
            indicators=indicators,
            action_required=action
        )
        
        # Trigger all registered callbacks
        for callback in self.regime_callbacks:
            try:
                callback(change)
            except Exception as e:
                self.logger.error(f"Regime callback failed: {e}")
    
    def _get_regime_action(
        self,
        old_regime: MarketRegime,
        new_regime: MarketRegime
    ) -> str:
        """Determine what action to take on regime change"""
        
        # CHOPPY → TRENDING: Switch to momentum strategy
        if old_regime == MarketRegime.CHOPPY and new_regime == MarketRegime.TRENDING:
            return "switch_to_momentum"
        
        # TRENDING → CHOPPY: Switch to mean-reversion/grid
        if old_regime == MarketRegime.TRENDING and new_regime == MarketRegime.CHOPPY:
            return "switch_to_range_strategies"
        
        # Any → VOLATILE: Reduce leverage, tighten stops
        if new_regime == MarketRegime.VOLATILE:
            return "reduce_risk_volatile"
        
        # VOLATILE → Any: Can increase leverage again
        if old_regime == MarketRegime.VOLATILE:
            return "restore_normal_risk"
        
        return "re_evaluate_strategy"
    
    def register_callback(self, callback: Callable[[RegimeChange], None]) -> None:
        """Register callback for regime changes"""
        self.regime_callbacks.append(callback)
        self.logger.info(f"Registered regime change callback: {callback.__name__}")
    
    def get_current_regime(self, symbol: str) -> MarketRegime:
        """Get last detected regime for symbol"""
        return self.current_regimes.get(symbol, MarketRegime.UNKNOWN)


# Singleton instance
_regime_detector: Optional[LiveRegimeDetector] = None


def get_live_regime_detector() -> LiveRegimeDetector:
    """Get or create singleton regime detector"""
    global _regime_detector
    if _regime_detector is None:
        _regime_detector = LiveRegimeDetector()
    return _regime_detector


def detect_regime_live(
    symbol: str,
    market_ctx: Dict[str, Any],
    force_check: bool = False
) -> MarketRegime:
    """
    Convenience function for live regime detection.
    
    Returns current market regime and handles regime changes automatically.
    """
    detector = get_live_regime_detector()
    return detector.detect_regime(symbol, market_ctx, force_check)


def register_regime_callback(callback: Callable[[RegimeChange], None]) -> None:
    """Register callback to be notified on regime changes"""
    detector = get_live_regime_detector()
    detector.register_callback(callback)
