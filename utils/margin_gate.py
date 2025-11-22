#!/usr/bin/env python3
"""
Margin Gate - Automatic Resource Management Based on Available Margin
=====================================================================
MetaBrain v9.2.6 Feature: Smart Resource Pausing

When there's no available margin:
- PAUSE scanning (gpt_auto_suggest.py)
- PAUSE brain analysis (gpt5_orchestrator.py)
- PAUSE fill monitoring (fills_watcher.py)
- ONLY run essential services (position_monitor, fills_watcher monitoring)

When margin returns (from profit or new deposit):
- RESUME all scanning automatically
- No manual intervention needed

This prevents wasting API resources and keeps system efficient.
"""

import logging
import asyncio
from typing import Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger("margin_gate")

# Minimum margin required to continue scanning
MIN_MARGIN_USDT = 10.0  # Must have at least $10 margin available
CHECK_INTERVAL_SEC = 30  # Check margin every 30 seconds
SLEEP_WHEN_PAUSED_SEC = 60  # Sleep 60 seconds when paused


class MarginGate:
    """
    Automatic margin gate - pauses/resumes scanning based on available balance.
    """
    
    def __init__(self):
        self.logger = logger
        self.is_paused = False
        self.pause_reason = ""
        self.last_check = None
        self.margin_trend = []  # Last 5 margin checks for trend analysis
        
    async def check_can_scan(self) -> Dict[str, Any]:
        """
        Check if we can continue scanning. 
        
        Returns:
        {
            'can_scan': bool,
            'available_margin': float,
            'reason': str,
            'pause_duration': float (seconds if paused)
        }
        """
        try:
            from utils.binance_client import futures_account
            
            # Get account info
            account = futures_account()
            if not account:
                return {
                    'can_scan': False,
                    'available_margin': 0.0,
                    'reason': 'Cannot fetch account info',
                    'pause_duration': CHECK_INTERVAL_SEC
                }
            
            # Calculate available margin
            total_wallet_balance = float(account.get('totalWalletBalance', 0))
            total_unrealized_pnl = float(account.get('totalUnrealizedProfit', 0))
            total_maintenance_margin = float(account.get('totalMaintMargin', 0))
            
            available_margin = total_wallet_balance + total_unrealized_pnl - total_maintenance_margin
            
            # Track trend (last 5 checks)
            self.margin_trend.append(available_margin)
            if len(self.margin_trend) > 5:
                self.margin_trend.pop(0)
            
            self.last_check = datetime.now()
            
            # Decision logic
            if available_margin < MIN_MARGIN_USDT:
                self.is_paused = True
                reason = f"Insufficient margin: ${available_margin:.2f} < ${MIN_MARGIN_USDT:.2f}"
                self.pause_reason = reason
                
                self.logger.warning(
                    f"🔴 MARGIN GATE CLOSED | {reason} | "
                    f"Wallet: ${total_wallet_balance:.2f} | "
                    f"PnL: {total_unrealized_pnl:+.2f} | "
                    f"Maintenance: ${total_maintenance_margin:.2f}"
                )
                
                return {
                    'can_scan': False,
                    'available_margin': available_margin,
                    'reason': reason,
                    'pause_duration': SLEEP_WHEN_PAUSED_SEC,
                    'wallet_balance': total_wallet_balance,
                    'unrealized_pnl': total_unrealized_pnl,
                    'maintenance_margin': total_maintenance_margin
                }
            
            # Margin is sufficient
            if self.is_paused:
                self.logger.info(
                    f"🟢 MARGIN GATE OPENED | Margin returned: ${available_margin:.2f} | "
                    f"Resuming all scanning..."
                )
                self.is_paused = False
                self.pause_reason = ""
            
            return {
                'can_scan': True,
                'available_margin': available_margin,
                'reason': 'Margin sufficient',
                'wallet_balance': total_wallet_balance,
                'unrealized_pnl': total_unrealized_pnl,
                'maintenance_margin': total_maintenance_margin
            }
            
        except Exception as e:
            self.logger.error(f"❌ Margin check failed: {e}")
            # Fail-safe: allow scanning if we can't check
            return {
                'can_scan': True,
                'available_margin': 0.0,
                'reason': f'Check failed (allowed): {e}'
            }
    
    def get_sleep_time_if_paused(self) -> float:
        """If paused, return sleep duration. Otherwise 0."""
        if self.is_paused:
            return SLEEP_WHEN_PAUSED_SEC
        return 0.0
    
    def get_status(self) -> Dict[str, Any]:
        """Get current gate status"""
        return {
            'is_paused': self.is_paused,
            'pause_reason': self.pause_reason,
            'last_check': self.last_check,
            'margin_trend': self.margin_trend[-3:] if self.margin_trend else [],
            'min_margin_required': MIN_MARGIN_USDT
        }


# Singleton instance
_gate: Any = None


def get_margin_gate() -> MarginGate:
    """Get or create singleton margin gate"""
    global _gate
    if _gate is None:
        _gate = MarginGate()
    return _gate


async def check_can_scan() -> bool:
    """Quick check - can we scan? (True/False only)"""
    gate = get_margin_gate()
    result = await gate.check_can_scan()
    return result['can_scan']


__all__ = [
    'MarginGate',
    'get_margin_gate',
    'check_can_scan',
    'MIN_MARGIN_USDT',
    'CHECK_INTERVAL_SEC',
    'SLEEP_WHEN_PAUSED_SEC'
]
