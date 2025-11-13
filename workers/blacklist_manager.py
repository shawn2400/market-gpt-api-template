"""
Dynamic Blacklist Manager - Auto-Blacklist Poor Performers
===========================================================
Automatically blacklists symbols with poor performance for 24 hours
to prevent repeated losses on weak symbols.

Blacklist Criteria:
- 3+ consecutive losses on same symbol
- Win rate < 25% with 5+ trades
- Avg loss > 2x avg win

Author: AlgoGPT Team
"""

import logging
import os
import json
from typing import Dict, List, Set
from datetime import datetime, timedelta

from utils.performance_tracker import get_performance_tracker

LOGGER = logging.getLogger("blacklist_manager")


class BlacklistManager:
    """
    Manages auto-blacklist of poor-performing symbols with TTL.
    
    Features:
    - 24h blacklist duration (configurable)
    - Auto-removal after TTL expires
    - Multiple blacklist reasons
    - Integration with watchlist_utils
    """
    
    def __init__(self):
        self.logger = LOGGER
        self.performance_tracker = get_performance_tracker()
        
        self.blacklist_file = os.getenv(
            "AUTO_BLACKLIST_FILE",
            "/tmp/auto_blacklist.json"
        )
        
        self.blacklist_duration_hours = int(os.getenv("BLACKLIST_DURATION_HOURS", "24"))
        
        self.blacklist: Dict[str, Dict] = {}
        self._load_blacklist()
    
    def auto_manage_blacklist(self, days: int = 7) -> Dict:
        """
        Analyze performance and update blacklist automatically.
        
        Args:
            days: Lookback period for analysis
            
        Returns:
            Dict with blacklist updates (added, removed, active)
        """
        self.logger.info("🚫 Running auto-blacklist analysis")
        
        # Remove expired entries first
        removed_expired = self._remove_expired_entries()
        
        # Analyze symbols for blacklist consideration
        all_symbol_stats = self.performance_tracker.get_all_symbol_stats(
            days=days,
            min_trades=3
        )
        
        newly_blacklisted = []
        
        for symbol, stats in all_symbol_stats.items():
            # Skip if already blacklisted
            if symbol in self.blacklist:
                continue
            
            # Check blacklist criteria
            should_blacklist, reason = self._should_blacklist(stats)
            
            if should_blacklist:
                self._add_to_blacklist(symbol, reason, stats)
                newly_blacklisted.append({
                    "symbol": symbol,
                    "reason": reason,
                    "win_rate": stats["win_rate"],
                    "consecutive_losses": stats["consecutive_losses"]
                })
        
        self.logger.info(
            f"✅ Blacklist updated: "
            f"+{len(newly_blacklisted)} added, "
            f"-{removed_expired} expired, "
            f"{len(self.blacklist)} active"
        )
        
        return {
            "newly_blacklisted": newly_blacklisted,
            "expired_removed": removed_expired,
            "active_blacklist": list(self.blacklist.keys()),
            "total_blacklisted": len(self.blacklist)
        }
    
    def _should_blacklist(self, stats: Dict) -> tuple[bool, str]:
        """
        Determine if a symbol should be blacklisted.
        
        Returns:
            (should_blacklist, reason) tuple
        """
        win_rate = stats["win_rate"]
        total_trades = stats["total_trades"]
        consecutive_losses = stats["consecutive_losses"]
        avg_profit = stats["avg_profit"]
        avg_loss = abs(stats["avg_loss"])
        
        # Criterion 1: 3+ consecutive losses
        if consecutive_losses >= 3:
            return (True, f"consecutive_losses_{consecutive_losses}")
        
        # Criterion 2: Very low win rate with enough trades
        if total_trades >= 5 and win_rate < 25:
            return (True, f"low_win_rate_{win_rate:.1f}%")
        
        # Criterion 3: Average loss > 2x average win
        if avg_profit > 0 and avg_loss > (2 * avg_profit):
            return (True, f"unfavorable_pl_ratio_{avg_loss:.2f}>{avg_profit:.2f}")
        
        # Criterion 4: Declining trend with poor performance
        if stats["recent_trend"] == "declining" and win_rate < 35:
            return (True, f"declining_performance")
        
        return (False, "")
    
    def _add_to_blacklist(self, symbol: str, reason: str, stats: Dict):
        """Add symbol to blacklist with TTL"""
        expires_at = datetime.utcnow() + timedelta(hours=self.blacklist_duration_hours)
        
        self.blacklist[symbol] = {
            "reason": reason,
            "added_at": datetime.utcnow().isoformat(),
            "expires_at": expires_at.isoformat(),
            "stats": {
                "win_rate": stats["win_rate"],
                "total_trades": stats["total_trades"],
                "consecutive_losses": stats["consecutive_losses"]
            }
        }
        
        self._save_blacklist()
        
        self.logger.warning(
            f"🚫 Blacklisted {symbol}: {reason} "
            f"(expires in {self.blacklist_duration_hours}h)"
        )
    
    def _remove_expired_entries(self) -> int:
        """Remove blacklist entries that have expired"""
        now = datetime.utcnow()
        
        expired_symbols = [
            symbol for symbol, info in self.blacklist.items()
            if datetime.fromisoformat(info["expires_at"]) <= now
        ]
        
        for symbol in expired_symbols:
            del self.blacklist[symbol]
            self.logger.info(f"✅ {symbol} removed from blacklist (expired)")
        
        if expired_symbols:
            self._save_blacklist()
        
        return len(expired_symbols)
    
    def is_blacklisted(self, symbol: str) -> bool:
        """Check if a symbol is currently blacklisted"""
        if symbol not in self.blacklist:
            return False
        
        # Check if expired
        expires_at = datetime.fromisoformat(self.blacklist[symbol]["expires_at"])
        if datetime.utcnow() >= expires_at:
            del self.blacklist[symbol]
            self._save_blacklist()
            return False
        
        return True
    
    def get_blacklist_reason(self, symbol: str) -> str:
        """Get blacklist reason for a symbol"""
        if symbol in self.blacklist:
            return self.blacklist[symbol]["reason"]
        return ""
    
    def get_active_blacklist(self) -> List[Dict]:
        """Get all active blacklisted symbols with details"""
        self._remove_expired_entries()
        
        return [
            {
                "symbol": symbol,
                **info
            }
            for symbol, info in self.blacklist.items()
        ]
    
    def manual_remove(self, symbol: str) -> bool:
        """Manually remove a symbol from blacklist"""
        if symbol in self.blacklist:
            del self.blacklist[symbol]
            self._save_blacklist()
            self.logger.info(f"✅ {symbol} manually removed from blacklist")
            return True
        return False
    
    def manual_add(self, symbol: str, reason: str, hours: int = None) -> bool:
        """Manually add a symbol to blacklist"""
        if hours is None:
            hours = self.blacklist_duration_hours
        
        expires_at = datetime.utcnow() + timedelta(hours=hours)
        
        self.blacklist[symbol] = {
            "reason": f"manual: {reason}",
            "added_at": datetime.utcnow().isoformat(),
            "expires_at": expires_at.isoformat(),
            "stats": {}
        }
        
        self._save_blacklist()
        self.logger.warning(f"🚫 {symbol} manually blacklisted: {reason} ({hours}h)")
        return True
    
    def _save_blacklist(self):
        """Save blacklist to disk"""
        try:
            data = {
                "blacklist": self.blacklist,
                "updated_at": datetime.utcnow().isoformat()
            }
            with open(self.blacklist_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to save blacklist: {e}")
    
    def _load_blacklist(self):
        """Load blacklist from disk"""
        try:
            if os.path.exists(self.blacklist_file):
                with open(self.blacklist_file, "r") as f:
                    data = json.load(f)
                    self.blacklist = data.get("blacklist", {})
                    
                    # Remove expired on load
                    self._remove_expired_entries()
                    
                    self.logger.info(f"Loaded {len(self.blacklist)} blacklisted symbols")
        except Exception as e:
            self.logger.warning(f"Failed to load blacklist: {e}")
            self.blacklist = {}


def update_blacklist(days: int = 7) -> Dict:
    """
    Convenience function to update blacklist.
    
    Args:
        days: Lookback period
        
    Returns:
        Blacklist update summary
    """
    manager = BlacklistManager()
    return manager.auto_manage_blacklist(days=days)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = update_blacklist(days=7)
    print(f"Blacklist Update: {result}")
