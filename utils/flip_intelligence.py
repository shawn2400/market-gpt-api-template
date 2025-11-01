"""
Position Flip Intelligence
===========================
Decides when to automatically flip positions (close LONG, open SHORT or vice versa).

Rules for flipping:
1. Market regime MUST have changed significantly
2. All systems MUST agree (Market Intel, Portfolio, Performance)
3. Minimum time since last flip (cooldown)
4. Current position can be exited profitably or at breakeven
5. New direction has strong conviction (high quality setup)

This prevents:
- Flipping every 5 minutes (whipsaw)
- Flipping in choppy/unclear markets
- Flipping when it would lock in losses
- Flip when portfolio is overexposed

Author: AlgoGPT Team
Level: Hedge Fund Grade
"""

import logging
import os
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass

LOGGER = logging.getLogger("flip_intelligence")


@dataclass
class FlipDecision:
    """Decision on whether to flip position"""
    should_flip: bool
    reason: str
    new_side: Optional[str]  # "LONG" or "SHORT"
    exit_price: Optional[float]  # Where to exit current position
    confidence: float  # 0-100
    conditions_met: Dict[str, bool]  # Which conditions passed/failed


class FlipIntelligence:
    """
    Analyzes market conditions and decides if position flip is warranted.
    
    A flip means:
    1. Close current position (LONG/SHORT)
    2. Open opposite position (SHORT/LONG) immediately
    
    This is aggressive but can be very profitable when done right.
    """
    
    def __init__(self):
        self.logger = LOGGER
        
        # Configuration
        self.flip_enabled = os.getenv("ENABLE_AUTO_FLIP", "1") == "1"
        self.min_flip_interval_min = int(os.getenv("MIN_FLIP_INTERVAL_MIN", "30"))  # 30 minutes minimum
        self.min_regime_change_score = float(os.getenv("MIN_REGIME_CHANGE_SCORE", "0.6"))  # 60% change
        self.min_new_setup_quality = float(os.getenv("MIN_FLIP_SETUP_QUALITY", "7.0"))  # Quality 7/10
        self.require_profit_or_be = os.getenv("REQUIRE_PROFIT_OR_BE", "1") == "1"  # Only flip if profitable/BE
        
        # State tracking
        self.last_flip_time: Dict[str, datetime] = {}  # symbol → last flip timestamp
        self.flip_history: list = []
    
    def should_flip_position(
        self,
        symbol: str,
        current_side: str,  # "LONG" or "SHORT"
        current_entry: float,
        current_price: float,
        
        # Current market state
        old_regime: str,
        old_mood: str,
        old_trend_strength: float,
        
        # New market state
        new_regime: str,
        new_mood: str,
        new_trend_strength: float,
        
        # New setup (opposite direction)
        new_setup_quality: Optional[float] = None,
        new_setup_rr: Optional[float] = None,
        new_ai_confidence: Optional[float] = None,
        
        # Portfolio state
        can_add_position: bool = True,
        current_pnl_pct: Optional[float] = None
        
    ) -> FlipDecision:
        """
        Decide if we should flip from current position to opposite.
        
        Returns:
            FlipDecision with should_flip, reason, and details
        """
        if not self.flip_enabled:
            return FlipDecision(
                should_flip=False,
                reason="Auto-flip disabled",
                new_side=None,
                exit_price=None,
                confidence=0.0,
                conditions_met={"enabled": False}
            )
        
        conditions = {}
        reasons = []
        
        # 1. Check cooldown (don't flip too frequently)
        cooldown_ok, cooldown_reason = self._check_flip_cooldown(symbol)
        conditions["cooldown"] = cooldown_ok
        if not cooldown_ok:
            reasons.append(cooldown_reason)
        
        # 2. Check if market regime changed significantly
        regime_changed, regime_reason = self._check_regime_change(
            old_regime, old_mood, old_trend_strength,
            new_regime, new_mood, new_trend_strength
        )
        conditions["regime_change"] = regime_changed
        if not regime_changed:
            reasons.append(regime_reason)
        
        # 3. Check if new setup is high quality
        new_setup_ok, new_setup_reason = self._check_new_setup_quality(
            new_setup_quality, new_setup_rr, new_ai_confidence
        )
        conditions["new_setup_quality"] = new_setup_ok
        if not new_setup_ok:
            reasons.append(new_setup_reason)
        
        # 4. Check if we can exit current position profitably
        can_exit_ok, exit_reason, exit_price = self._check_can_exit(
            current_side, current_entry, current_price, current_pnl_pct
        )
        conditions["can_exit_profitably"] = can_exit_ok
        if not can_exit_ok:
            reasons.append(exit_reason)
        
        # 5. Check portfolio capacity
        portfolio_ok = can_add_position
        conditions["portfolio_capacity"] = portfolio_ok
        if not portfolio_ok:
            reasons.append("Portfolio full, cannot add opposite position")
        
        # 6. Check direction makes sense
        new_side = "SHORT" if current_side == "LONG" else "LONG"
        direction_ok, direction_reason = self._check_direction_makes_sense(
            new_side, new_regime, new_mood
        )
        conditions["direction_makes_sense"] = direction_ok
        if not direction_ok:
            reasons.append(direction_reason)
        
        # Decision: ALL conditions must pass
        should_flip = all(conditions.values())
        
        if should_flip:
            # Record flip
            self.last_flip_time[symbol] = datetime.utcnow()
            self.flip_history.append({
                "symbol": symbol,
                "from_side": current_side,
                "to_side": new_side,
                "timestamp": datetime.utcnow().isoformat(),
                "regime_change": f"{old_regime}→{new_regime}",
                "mood_change": f"{old_mood}→{new_mood}"
            })
            
            confidence = self._calculate_flip_confidence(
                regime_changed, new_setup_quality or 0,
                new_setup_rr or 0, new_ai_confidence or 0
            )
            
            reason = (
                f"FLIP APPROVED: Market changed {old_regime}/{old_mood} → {new_regime}/{new_mood}, "
                f"new {new_side} setup Q={new_setup_quality:.1f}, exit @ {exit_price}"
            )
            
            self.logger.info(f"🔄 {reason}")
        else:
            confidence = 0.0
            reason = "FLIP REJECTED: " + "; ".join(reasons)
            self.logger.info(f"❌ {reason}")
        
        return FlipDecision(
            should_flip=should_flip,
            reason=reason,
            new_side=new_side if should_flip else None,
            exit_price=exit_price if should_flip else None,
            confidence=confidence,
            conditions_met=conditions
        )
    
    def _check_flip_cooldown(self, symbol: str) -> Tuple[bool, str]:
        """Check if enough time passed since last flip"""
        if symbol not in self.last_flip_time:
            return (True, "")
        
        time_since_flip = datetime.utcnow() - self.last_flip_time[symbol]
        min_interval = timedelta(minutes=self.min_flip_interval_min)
        
        if time_since_flip < min_interval:
            minutes_left = (min_interval - time_since_flip).total_seconds() / 60
            return (False, f"Flip cooldown: {minutes_left:.0f} min remaining")
        
        return (True, "")
    
    def _check_regime_change(
        self,
        old_regime: str,
        old_mood: str,
        old_strength: float,
        new_regime: str,
        new_mood: str,
        new_strength: float
    ) -> Tuple[bool, str]:
        """Check if market regime changed significantly"""
        
        # Score regime change (0-1)
        regime_change_score = 0.0
        
        # Regime changed?
        if old_regime != new_regime:
            regime_change_score += 0.4
        
        # Mood changed?
        if old_mood != new_mood:
            regime_change_score += 0.3
        
        # Trend strength changed significantly?
        strength_delta = abs(new_strength - old_strength)
        if strength_delta > 20:  # 20+ point change
            regime_change_score += 0.3
        
        if regime_change_score >= self.min_regime_change_score:
            return (True, "")
        else:
            return (
                False,
                f"Regime change insufficient (score={regime_change_score:.2f} < {self.min_regime_change_score})"
            )
    
    def _check_new_setup_quality(
        self,
        quality: Optional[float],
        rr: Optional[float],
        ai_conf: Optional[float]
    ) -> Tuple[bool, str]:
        """Check if new setup (opposite direction) is high quality"""
        
        if quality is None:
            return (False, "No new setup available")
        
        if quality < self.min_new_setup_quality:
            return (
                False,
                f"New setup quality too low (Q={quality:.1f} < {self.min_new_setup_quality})"
            )
        
        if rr is not None and rr < 1.5:
            return (False, f"New setup RR too low (RR={rr:.2f} < 1.5)")
        
        if ai_conf is not None and ai_conf < 60:
            return (False, f"New setup AI confidence too low ({ai_conf:.0f}% < 60%)")
        
        return (True, "")
    
    def _check_can_exit(
        self,
        side: str,
        entry: float,
        current_price: float,
        pnl_pct: Optional[float]
    ) -> Tuple[bool, str, Optional[float]]:
        """Check if we can exit current position profitably or at BE"""
        
        # Calculate P&L if not provided
        if pnl_pct is None:
            if side == "LONG":
                pnl_pct = ((current_price - entry) / entry) * 100
            else:  # SHORT
                pnl_pct = ((entry - current_price) / entry) * 100
        
        # Require profit or breakeven
        if self.require_profit_or_be and pnl_pct < -0.5:  # Allow -0.5% (fees)
            return (
                False,
                f"Cannot exit at loss (PnL={pnl_pct:+.2f}%)",
                None
            )
        
        # Exit at current price
        return (True, "", current_price)
    
    def _check_direction_makes_sense(
        self,
        new_side: str,
        new_regime: str,
        new_mood: str
    ) -> Tuple[bool, str]:
        """Check if new direction aligns with market conditions"""
        
        # LONG should align with bullish conditions
        if new_side == "LONG":
            if new_mood == "bearish" and new_regime == "trending":
                return (False, "LONG doesn't make sense in trending bearish market")
        
        # SHORT should align with bearish conditions
        if new_side == "SHORT":
            if new_mood == "bullish" and new_regime == "trending":
                return (False, "SHORT doesn't make sense in trending bullish market")
        
        # Sideways/choppy markets - both directions can work
        # Neutral mood - both directions can work
        
        return (True, "")
    
    def _calculate_flip_confidence(
        self,
        regime_changed: bool,
        new_quality: float,
        new_rr: float,
        new_ai_conf: float
    ) -> float:
        """Calculate confidence in flip decision (0-100)"""
        
        confidence = 50.0  # Base
        
        if regime_changed:
            confidence += 20.0
        
        if new_quality >= 8.0:
            confidence += 15.0
        elif new_quality >= 7.0:
            confidence += 10.0
        
        if new_rr >= 2.0:
            confidence += 10.0
        elif new_rr >= 1.5:
            confidence += 5.0
        
        if new_ai_conf >= 75:
            confidence += 10.0
        elif new_ai_conf >= 65:
            confidence += 5.0
        
        return min(100.0, confidence)
    
    def get_flip_stats(self) -> Dict:
        """Get statistics about flips"""
        if not self.flip_history:
            return {"total_flips": 0}
        
        return {
            "total_flips": len(self.flip_history),
            "recent_flips": self.flip_history[-5:] if len(self.flip_history) >= 5 else self.flip_history
        }


# Global instance
_flip_intelligence = None

def get_flip_intelligence() -> FlipIntelligence:
    """Get singleton instance"""
    global _flip_intelligence
    if _flip_intelligence is None:
        _flip_intelligence = FlipIntelligence()
    return _flip_intelligence
