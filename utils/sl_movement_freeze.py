#!/usr/bin/env python3
"""
❄️ SL Movement Freeze - Prevents unnecessary SL changes
=======================================================

Tracks existing SL and prevents moving it unless there's a significant improvement.
- SL should only move TIGHTER (more protective)
- Prevent moving SL LOOSER (more risky)
- Only update if improvement > FREEZE_THRESHOLD (default 5%)
"""

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger("algogpt.sl_freeze")

# Minimum improvement percentage to justify SL change (5%)
FREEZE_THRESHOLD = 0.05


class SLMovementFreezer:
    """Prevents unnecessary SL changes."""
    
    def __init__(self):
        """Track current SL by symbol."""
        self.position_sl: Dict[str, float] = {}  # symbol -> current SL
    
    def set_current_sl(self, symbol: str, sl_price: float):
        """Record the current SL for a position."""
        self.position_sl[symbol] = sl_price
        logger.info(f"❄️ SL Freezer: Recorded SL for {symbol} @ {sl_price:.8f}")
    
    def should_update_sl(
        self,
        symbol: str,
        new_sl: float,
        entry_price: float,
        position_side: str
    ) -> Tuple[bool, str]:
        """
        ❄️ Check if SL should be updated.
        
        Returns: (should_update, reason)
        """
        current_sl = self.position_sl.get(symbol)
        
        # No existing SL - always place
        if current_sl is None:
            return True, f"No existing SL, placing new SL @ {new_sl:.8f}"
        
        # Validate SL prices
        if new_sl <= 0 or current_sl <= 0:
            return False, f"Invalid SL values: new={new_sl:.8f}, current={current_sl:.8f}"
        
        # 🔒 CRITICAL: Check if new SL is LOOSER (more risky) than current
        if position_side == "LONG":
            # For LONG: Higher SL = tighter protection
            # Looser = SL moved DOWN (closer to 0)
            if new_sl < current_sl:
                return False, f"❌ FROZEN: New SL {new_sl:.8f} < Current {current_sl:.8f} (LOOSENING protection, BLOCKED)"
            
            # Check if tightening enough to justify update
            tightening_pct = (current_sl - new_sl) / entry_price if entry_price > 0 else 0
            if tightening_pct > 0:  # It's LOOSER, already blocked
                return False, f"SL is loosening, skipped"
            
            # It's tightening - check if significant
            improvement_pct = (new_sl - current_sl) / entry_price if entry_price > 0 else 0
            if improvement_pct < FREEZE_THRESHOLD:
                return False, f"⚠️ FROZEN: Improvement {improvement_pct*100:.2f}% < threshold {FREEZE_THRESHOLD*100:.0f}%, skipping SL update"
        
        else:  # SHORT
            # For SHORT: Lower SL = tighter protection
            # Looser = SL moved UP (further from 0)
            if new_sl > current_sl:
                return False, f"❌ FROZEN: New SL {new_sl:.8f} > Current {current_sl:.8f} (LOOSENING protection, BLOCKED)"
            
            # Check if tightening enough to justify update
            improvement_pct = (current_sl - new_sl) / entry_price if entry_price > 0 else 0
            if improvement_pct < FREEZE_THRESHOLD:
                return False, f"⚠️ FROZEN: Improvement {improvement_pct*100:.2f}% < threshold {FREEZE_THRESHOLD*100:.0f}%, skipping SL update"
        
        logger.info(f"✅ SL Update APPROVED: {symbol} {position_side} from {current_sl:.8f} → {new_sl:.8f}")
        return True, f"SL update approved (tightening by {improvement_pct*100:.2f}%)"
    
    def clear_position(self, symbol: str):
        """Remove SL tracking when position is closed."""
        if symbol in self.position_sl:
            del self.position_sl[symbol]
            logger.info(f"❄️ SL Freezer: Cleared SL for {symbol} (position closed)")


# Global instance
_freezer: Optional[SLMovementFreezer] = None


def get_sl_freezer() -> SLMovementFreezer:
    """Get or create SL freezer instance."""
    global _freezer
    if _freezer is None:
        _freezer = SLMovementFreezer()
    return _freezer


__all__ = ["SLMovementFreezer", "get_sl_freezer", "FREEZE_THRESHOLD"]
