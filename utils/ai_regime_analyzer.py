"""
AI Market Regime Analyzer - Real-time Regime Shift Detection
============================================================
Detects market regime changes automatically and tracks confidence over time

Features:
- Real-time regime analysis (TRENDING/CHOPPY/VOLATILE/SIDEWAYS)
- Automatic shift detection (CHOPPY → TRENDING, etc.)
- Confidence scoring with historical tracking
- Regime stability assessment
- Integration with existing MarketIntelligence

Author: AlgoGPT Team - MetaBrain v9.1
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import deque

LOGGER = logging.getLogger("ai_regime_analyzer")


@dataclass
class RegimeSnapshot:
    """Single regime observation"""
    timestamp: datetime
    symbol: str
    regime: str  # trending/choppy/volatile/sideways
    mood: str    # bullish/bearish/neutral
    confidence: float  # 0-100
    trend_strength: float  # 0-100
    volatility: str  # high/medium/low
    adx: float
    atr_pct: float


@dataclass
class RegimeShift:
    """Detected regime change"""
    timestamp: datetime
    symbol: str
    from_regime: str
    to_regime: str
    confidence: float
    reason: str
    trading_impact: str  # Description of how this affects trading


class AIRegimeAnalyzer:
    """
    Advanced regime analyzer with shift detection and confidence tracking
    """
    
    def __init__(self, history_window: int = 50):
        """
        Args:
            history_window: Number of recent observations to keep per symbol
        """
        self.logger = LOGGER
        self.history_window = history_window
        
        # Store recent regime history per symbol
        # {symbol: deque([RegimeSnapshot, ...])}
        self.regime_history: Dict[str, deque] = {}
        
        # Store recent regime shifts
        # {symbol: [RegimeShift, ...]}
        self.regime_shifts: Dict[str, List[RegimeShift]] = {}
    
    def analyze_with_shift_detection(
        self,
        symbol: str,
        context: Dict[str, Any],
        market_condition: Optional[Any] = None
    ) -> Tuple[RegimeSnapshot, Optional[RegimeShift]]:
        """
        Analyze current regime and detect shifts from previous state
        
        Args:
            symbol: Trading symbol
            context: Market data dict
            market_condition: Pre-computed MarketCondition (optional)
            
        Returns:
            (current_snapshot, detected_shift_or_none)
        """
        from utils.market_intelligence import get_market_intelligence
        
        # Get market analysis
        if market_condition is None:
            mi = get_market_intelligence()
            market_condition = mi.analyze_market(context)
        
        # Create current snapshot
        current_snapshot = RegimeSnapshot(
            timestamp=datetime.now(),
            symbol=symbol,
            regime=market_condition.regime,
            mood=market_condition.mood,
            confidence=market_condition.confidence,
            trend_strength=market_condition.trend_strength,
            volatility=market_condition.volatility,
            adx=context.get("adx", 20.0),
            atr_pct=context.get("atr_percent") or context.get("atr_pct", 2.5)
        )
        
        # Initialize history for symbol if needed
        if symbol not in self.regime_history:
            self.regime_history[symbol] = deque(maxlen=self.history_window)
            self.regime_shifts[symbol] = []
        
        # Detect regime shift
        shift = None
        if len(self.regime_history[symbol]) > 0:
            previous = self.regime_history[symbol][-1]
            
            # Check if regime changed
            if previous.regime != current_snapshot.regime:
                shift = self._create_regime_shift(
                    symbol=symbol,
                    from_snapshot=previous,
                    to_snapshot=current_snapshot
                )
                
                # Store shift
                self.regime_shifts[symbol].append(shift)
                
                # Keep only recent shifts (last 20)
                self.regime_shifts[symbol] = self.regime_shifts[symbol][-20:]
                
                self.logger.info(
                    f"🔄 REGIME SHIFT [{symbol}]: "
                    f"{shift.from_regime.upper()} → {shift.to_regime.upper()} "
                    f"(confidence: {shift.confidence:.1f}%) | {shift.trading_impact}"
                )
        
        # Add to history
        self.regime_history[symbol].append(current_snapshot)
        
        # Log current state
        self.logger.info(
            f"📊 Regime [{symbol}]: {current_snapshot.regime.upper()} | "
            f"{current_snapshot.mood.upper()} | "
            f"Confidence: {current_snapshot.confidence:.1f}% | "
            f"Trend: {current_snapshot.trend_strength:.1f} | "
            f"ADX: {current_snapshot.adx:.1f} | ATR: {current_snapshot.atr_pct:.2f}%"
        )
        
        return current_snapshot, shift
    
    def _create_regime_shift(
        self,
        symbol: str,
        from_snapshot: RegimeSnapshot,
        to_snapshot: RegimeSnapshot
    ) -> RegimeShift:
        """
        Create RegimeShift with analysis of the change
        
        Returns:
            RegimeShift with trading impact description
        """
        
        # Calculate shift confidence (average of both states)
        confidence = (from_snapshot.confidence + to_snapshot.confidence) / 2.0
        
        # Analyze trading impact
        trading_impact = self._analyze_trading_impact(
            from_snapshot.regime,
            to_snapshot.regime,
            to_snapshot.mood
        )
        
        # Generate reason
        reason = self._generate_shift_reason(from_snapshot, to_snapshot)
        
        return RegimeShift(
            timestamp=to_snapshot.timestamp,
            symbol=symbol,
            from_regime=from_snapshot.regime,
            to_regime=to_snapshot.regime,
            confidence=confidence,
            reason=reason,
            trading_impact=trading_impact
        )
    
    def _analyze_trading_impact(
        self,
        from_regime: str,
        to_regime: str,
        mood: str
    ) -> str:
        """
        Analyze how regime shift impacts trading strategy
        
        Returns:
            Description of trading impact
        """
        
        # Shift matrix: (from, to) → impact
        shift_impacts = {
            ("choppy", "trending"): f"Switch to trend-following ({mood} bias)",
            ("choppy", "volatile"): "Increase caution, wider stops needed",
            ("choppy", "sideways"): "Continue range trading, tighter ranges",
            
            ("trending", "choppy"): "Switch to scalping/grid, trend ended",
            ("trending", "volatile"): "Maintain trend bias, widen stops",
            ("trending", "sideways"): "Switch to range trading, trend exhausted",
            
            ("sideways", "trending"): f"Breakout confirmed, follow {mood} trend",
            ("sideways", "choppy"): "Range unstable, wait for clarity",
            ("sideways", "volatile"): "Exit ranges, volatility spike",
            
            ("volatile", "trending"): f"Volatility cooling, follow {mood} trend",
            ("volatile", "choppy"): "Volatility settling, scalp carefully",
            ("volatile", "sideways"): "Entering range, look for boundaries",
        }
        
        key = (from_regime, to_regime)
        return shift_impacts.get(key, f"Regime change: {from_regime} → {to_regime}")
    
    def _generate_shift_reason(
        self,
        from_snapshot: RegimeSnapshot,
        to_snapshot: RegimeSnapshot
    ) -> str:
        """
        Generate human-readable reason for regime shift
        
        Returns:
            Reason string
        """
        
        # ADX change
        adx_delta = to_snapshot.adx - from_snapshot.adx
        
        # ATR change
        atr_delta = to_snapshot.atr_pct - from_snapshot.atr_pct
        
        # Trend change
        trend_delta = to_snapshot.trend_strength - from_snapshot.trend_strength
        
        reasons = []
        
        if abs(adx_delta) > 5:
            if adx_delta > 0:
                reasons.append(f"ADX increased +{adx_delta:.1f} (stronger trend)")
            else:
                reasons.append(f"ADX decreased {adx_delta:.1f} (weaker trend)")
        
        if abs(atr_delta) > 0.5:
            if atr_delta > 0:
                reasons.append(f"Volatility spiked +{atr_delta:.1f}%")
            else:
                reasons.append(f"Volatility cooled {atr_delta:.1f}%")
        
        if abs(trend_delta) > 15:
            if trend_delta > 0:
                reasons.append(f"Trend strengthened +{trend_delta:.1f}")
            else:
                reasons.append(f"Trend weakened {trend_delta:.1f}")
        
        if not reasons:
            reasons.append("Market structure changed")
        
        return "; ".join(reasons)
    
    def get_regime_stability(self, symbol: str, lookback: int = 10) -> float:
        """
        Calculate regime stability score (0-100)
        
        High score = regime is stable (hasn't changed recently)
        Low score = regime is unstable (frequent changes)
        
        Args:
            symbol: Trading symbol
            lookback: Number of recent observations to check
            
        Returns:
            Stability score 0-100
        """
        if symbol not in self.regime_history:
            return 50.0  # Neutral (no history)
        
        history = list(self.regime_history[symbol])
        if len(history) < 2:
            return 50.0
        
        # Look at recent N observations
        recent = history[-lookback:]
        
        # Count regime changes
        changes = 0
        for i in range(1, len(recent)):
            if recent[i].regime != recent[i-1].regime:
                changes += 1
        
        # More changes = less stability
        # 0 changes → 100% stability
        # All different → 0% stability
        max_possible_changes = len(recent) - 1
        if max_possible_changes == 0:
            return 100.0
        
        stability = 100.0 * (1.0 - (changes / max_possible_changes))
        
        return stability
    
    def get_recent_shifts(self, symbol: str, count: int = 5) -> List[RegimeShift]:
        """
        Get most recent regime shifts for symbol
        
        Args:
            symbol: Trading symbol
            count: Number of recent shifts to return
            
        Returns:
            List of recent RegimeShifts (newest first)
        """
        if symbol not in self.regime_shifts:
            return []
        
        return list(reversed(self.regime_shifts[symbol][-count:]))
    
    def should_wait_for_stability(
        self,
        symbol: str,
        min_stability: float = 70.0
    ) -> Tuple[bool, str]:
        """
        Check if we should wait for regime to stabilize before trading
        
        Args:
            symbol: Trading symbol
            min_stability: Minimum stability score required
            
        Returns:
            (should_wait, reason)
        """
        stability = self.get_regime_stability(symbol)
        
        if stability < min_stability:
            recent_shifts = self.get_recent_shifts(symbol, count=3)
            shift_count = len(recent_shifts)
            
            reason = (
                f"Regime unstable ({stability:.1f}% < {min_stability}%). "
                f"{shift_count} shifts in last 10 candles. Wait for clarity."
            )
            return True, reason
        
        return False, f"Regime stable ({stability:.1f}%)"


# Global instance
_ai_regime_analyzer = None


def get_ai_regime_analyzer() -> AIRegimeAnalyzer:
    """Get singleton instance of AIRegimeAnalyzer"""
    global _ai_regime_analyzer
    if _ai_regime_analyzer is None:
        _ai_regime_analyzer = AIRegimeAnalyzer()
    return _ai_regime_analyzer
