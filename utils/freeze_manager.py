# -*- coding: utf-8 -*-
"""
ULTRA-PLUS: Freeze Manager - Auto-freeze risky symbols with dynamic thaw.
Dynamic auto-activation when trading losses detected.
"""

import os
import logging
import time
from typing import Dict, Optional
from contextlib import suppress

logger = logging.getLogger(__name__)

# Dynamic config
ENABLE_FREEZE_MANAGER = os.getenv("ENABLE_FREEZE_MANAGER", "1") == "1"
FREEZE_DURATION_MINUTES = int(os.getenv("FREEZE_DURATION_MINUTES", "180"))  # 3 hours
FREEZE_THRESHOLD_PNL = float(os.getenv("FREEZE_THRESHOLD_PNL", "-0.8"))  # -80% loss


class FreezeManager:
    """
    Manages frozen symbols - symbols that are temporarily blocked from trading
    due to high-risk situations (recent losses, volatility spikes, etc).
    """
    
    def __init__(self):
        self.enabled = ENABLE_FREEZE_MANAGER
        self.frozen_symbols: Dict[str, Dict] = {}  # symbol -> {until_ts, reason}
    
    def freeze(self, symbol: str, minutes: int = FREEZE_DURATION_MINUTES, 
               reason: str = "manual") -> bool:
        """
        Freeze a symbol from trading.
        
        Args:
            symbol: Trading symbol (e.g., 'BTCUSDT')
            minutes: Duration in minutes (default: 3 hours)
            reason: Reason for freeze (for logging)
        
        Returns:
            True if freeze was applied
        """
        if not self.enabled:
            return False
        
        until_ts = time.time() + (minutes * 60)
        self.frozen_symbols[symbol] = {
            "until_ts": until_ts,
            "reason": reason,
            "frozen_at": time.time()
        }
        
        logger.warning(f"❄️  Symbol {symbol} frozen for {minutes}min: {reason}")
        return True
    
    def is_frozen(self, symbol: str) -> bool:
        """Check if symbol is currently frozen."""
        if not self.enabled or symbol not in self.frozen_symbols:
            return False
        
        freeze_data = self.frozen_symbols[symbol]
        
        # Check if freeze duration expired (auto-thaw)
        if time.time() >= freeze_data["until_ts"]:
            del self.frozen_symbols[symbol]
            logger.info(f"🔓 Symbol {symbol} automatically thawed")
            return False
        
        return True
    
    def auto_freeze_on_loss(self, symbol: str, pnl: float) -> bool:
        """
        Automatically freeze symbol if loss exceeds threshold.
        Dynamic activation on poor performance.
        
        Args:
            symbol: Trading symbol
            pnl: Position PnL
        
        Returns:
            True if auto-freeze was triggered
        """
        if not self.enabled or pnl > FREEZE_THRESHOLD_PNL:
            return False
        
        reason = f"severe_loss={pnl:.4f}"
        return self.freeze(symbol, FREEZE_DURATION_MINUTES, reason)
    
    def get_freeze_info(self, symbol: str) -> Optional[Dict]:
        """Get freeze information for a symbol."""
        if symbol not in self.frozen_symbols:
            return None
        
        data = self.frozen_symbols[symbol]
        time_remaining = data["until_ts"] - time.time()
        
        return {
            "symbol": symbol,
            "frozen": True,
            "reason": data["reason"],
            "time_remaining_seconds": max(0, int(time_remaining)),
            "frozen_since": data["frozen_at"]
        }
    
    def get_all_frozen(self) -> Dict[str, Dict]:
        """Get all currently frozen symbols."""
        # Clean up expired freezes
        expired = [s for s, d in self.frozen_symbols.items() 
                   if time.time() >= d["until_ts"]]
        for s in expired:
            del self.frozen_symbols[s]
        
        return self.frozen_symbols.copy()
    
    def unfreeze(self, symbol: str) -> bool:
        """Manually unfreeze a symbol."""
        if symbol in self.frozen_symbols:
            del self.frozen_symbols[symbol]
            logger.info(f"🔓 Symbol {symbol} manually unfrozen")
            return True
        return False
    
    def unfreeze_all(self) -> int:
        """Unfreeze all symbols. Returns count unfrozen."""
        count = len(self.frozen_symbols)
        self.frozen_symbols.clear()
        if count > 0:
            logger.info(f"🔓 All {count} symbols unfrozen")
        return count
    
    def reset(self) -> None:
        """Reset freeze manager state."""
        self.frozen_symbols.clear()
        logger.info("🔄 Freeze manager reset")


# Global singleton
_freeze_manager = None


def get_freeze_manager() -> FreezeManager:
    """Get or create global freeze manager (singleton)."""
    global _freeze_manager
    if _freeze_manager is None:
        _freeze_manager = FreezeManager()
        if ENABLE_FREEZE_MANAGER:
            logger.info("✅ Freeze Manager initialized (dynamic auto-activation enabled)")
        else:
            logger.info("ℹ️  Freeze Manager disabled")
    return _freeze_manager
