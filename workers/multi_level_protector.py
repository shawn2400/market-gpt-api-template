"""
Multi-Level Protection System - 3-Tier Risk Management
=======================================================
Implements Warning, Conservative, and Emergency protection modes
based on real-time performance monitoring.

Protection Levels:
- WARNING (win rate < 40%): Light restrictions
- CONSERVATIVE (win rate < 35%): Heavy restrictions
- EMERGENCY (win rate < 25% or 4+ consecutive losses): Trade halt

Author: AlgoGPT Team
"""

import logging
import os
from typing import Dict, Optional
from datetime import datetime
from enum import Enum

from utils.performance_tracker import get_performance_tracker
from config.ai_protections import AIProtectionManager

LOGGER = logging.getLogger("multi_level_protector")


class ProtectionLevel(Enum):
    """Protection mode levels"""
    NORMAL = "normal"
    WARNING = "warning"
    CONSERVATIVE = "conservative"
    EMERGENCY = "emergency"


class MultiLevelProtector:
    """
    Monitors performance and activates progressive protection levels.
    
    Activation Criteria:
    - NORMAL: Win rate >= 40%, < 2 consecutive losses
    - WARNING: Win rate 35-40%, or 2 consecutive losses
    - CONSERVATIVE: Win rate 25-35%, or 3 consecutive losses
    - EMERGENCY: Win rate < 25%, or 4+ consecutive losses, or daily loss > $500
    """
    
    def __init__(self):
        self.logger = LOGGER
        self.performance_tracker = get_performance_tracker()
        self.ai_protections = AIProtectionManager()
        
        self.current_level = ProtectionLevel.NORMAL
        self.level_changed_at: Optional[datetime] = None
    
    def check_and_activate_protections(self, days: int = 7) -> Dict:
        """
        Check current performance and activate appropriate protection level.
        
        Args:
            days: Lookback period for analysis
            
        Returns:
            Dict with protection status and actions taken
        """
        self.logger.info("🛡️ Running multi-level protection check")
        
        # Get performance metrics
        overall_stats = self.performance_tracker.get_win_rate(days=days)
        win_rate = overall_stats.get("win_rate", 0.0)
        total_trades = overall_stats.get("total_trades", 0)
        avg_loss = abs(overall_stats.get("avg_loss_usd", 0.0))
        
        consecutive_losses = self.performance_tracker.get_consecutive_losses(days=days)
        
        # Calculate daily PnL
        daily_pnl = self._calculate_daily_pnl()
        
        self.logger.info(
            f"📊 Metrics: Win Rate {win_rate:.1f}%, "
            f"Consecutive Losses: {consecutive_losses}, "
            f"Daily PnL: ${daily_pnl:+.2f}"
        )
        
        # Determine required protection level
        required_level = self._determine_protection_level(
            win_rate=win_rate,
            consecutive_losses=consecutive_losses,
            daily_pnl=daily_pnl,
            total_trades=total_trades
        )
        
        # Apply protection level if changed
        previous_level = self.current_level
        if required_level != self.current_level:
            self._activate_protection_level(required_level)
            self.level_changed_at = datetime.utcnow()
            
            self.logger.warning(
                f"🚨 Protection level changed: {previous_level.value} → {required_level.value}"
            )
        
        return {
            "current_level": required_level.value,
            "previous_level": previous_level.value,
            "level_changed": required_level != previous_level,
            "win_rate": win_rate,
            "consecutive_losses": consecutive_losses,
            "daily_pnl": daily_pnl,
            "total_trades": total_trades,
            "restrictions": self._get_level_restrictions(required_level)
        }
    
    def _determine_protection_level(
        self,
        win_rate: float,
        consecutive_losses: int,
        daily_pnl: float,
        total_trades: int
    ) -> ProtectionLevel:
        """Determine appropriate protection level based on metrics"""
        
        # Not enough data - use normal mode
        if total_trades < 3:
            return ProtectionLevel.NORMAL
        
        # EMERGENCY conditions
        if (win_rate < 25 or 
            consecutive_losses >= 4 or 
            daily_pnl < -500):
            return ProtectionLevel.EMERGENCY
        
        # CONSERVATIVE conditions
        if (win_rate < 35 or consecutive_losses >= 3):
            return ProtectionLevel.CONSERVATIVE
        
        # WARNING conditions
        if (win_rate < 40 or consecutive_losses >= 2):
            return ProtectionLevel.WARNING
        
        # Default to NORMAL
        return ProtectionLevel.NORMAL
    
    def _activate_protection_level(self, level: ProtectionLevel):
        """Apply restrictions for the given protection level"""
        self.current_level = level
        
        restrictions = self._get_level_restrictions(level)
        
        # Update AI protection settings
        self.ai_protections.update_settings({
            "max_leverage": restrictions["max_leverage"],
            "min_risk_reward": restrictions["min_rr"],
            "max_daily_trades": restrictions["max_daily_trades"],
            "allowed_strategies": restrictions["allowed_strategies"]
        })
        
        self.logger.info(f"✅ Protection level {level.value} activated")
        self.logger.info(f"   Max Leverage: {restrictions['max_leverage']}")
        self.logger.info(f"   Min RR: {restrictions['min_rr']}")
        self.logger.info(f"   Max Daily Trades: {restrictions['max_daily_trades']}")
    
    def _get_level_restrictions(self, level: ProtectionLevel) -> Dict:
        """Get restriction parameters for each protection level"""
        
        if level == ProtectionLevel.EMERGENCY:
            return {
                "max_leverage": 5,
                "min_rr": 3.0,
                "max_daily_trades": 0,  # Trade halt
                "allowed_strategies": [],  # None allowed
                "min_quality": 9.0,
                "description": "🚨 EMERGENCY: Trading halted until recovery"
            }
        
        elif level == ProtectionLevel.CONSERVATIVE:
            return {
                "max_leverage": 8,
                "min_rr": 2.5,
                "max_daily_trades": 3,
                "allowed_strategies": ["GRID", "Mean-Reversion"],  # Safe strategies only
                "min_quality": 7.0,
                "description": "⚠️ CONSERVATIVE: Heavy restrictions active"
            }
        
        elif level == ProtectionLevel.WARNING:
            return {
                "max_leverage": 12,
                "min_rr": 2.0,
                "max_daily_trades": 6,
                "allowed_strategies": ["GRID", "Mean-Reversion", "Trend-Following"],
                "min_quality": 5.5,
                "description": "⚠️ WARNING: Light restrictions active"
            }
        
        else:  # NORMAL
            return {
                "max_leverage": 15,
                "min_rr": 1.5,
                "max_daily_trades": 10,
                "allowed_strategies": ["ALL"],
                "min_quality": 4.5,
                "description": "✅ NORMAL: Full trading enabled"
            }
    
    def _calculate_daily_pnl(self) -> float:
        """Calculate today's total PnL"""
        from datetime import datetime, timedelta
        
        today = datetime.utcnow().date()
        
        daily_trades = [
            t for t in self.performance_tracker.trades
            if t.closed_at is not None
            and t.actual_pnl_usd is not None
            and datetime.fromisoformat(t.closed_at).date() == today
        ]
        
        if not daily_trades:
            return 0.0
        
        return sum(t.actual_pnl_usd for t in daily_trades)
    
    def get_current_status(self) -> Dict:
        """Get current protection status"""
        return {
            "level": self.current_level.value,
            "level_changed_at": self.level_changed_at.isoformat() if self.level_changed_at else None,
            "restrictions": self._get_level_restrictions(self.current_level)
        }


def check_protections(days: int = 7) -> Dict:
    """
    Convenience function to check and activate protections.
    
    Args:
        days: Lookback period
        
    Returns:
        Protection status dictionary
    """
    protector = MultiLevelProtector()
    return protector.check_and_activate_protections(days=days)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = check_protections(days=7)
    print(f"Protection Status: {result}")
