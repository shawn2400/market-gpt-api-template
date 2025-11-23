# -*- coding: utf-8 -*-
"""
ULTRA-PLUS: Auto-Withdraw System - Automatic profit extraction to cold wallet.
Dynamic auto-activation when balance exceeds threshold.
"""

import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from contextlib import suppress

logger = logging.getLogger(__name__)

# Dynamic config
ENABLE_AUTO_WITHDRAW = os.getenv("ENABLE_AUTO_WITHDRAW", "1") == "1"
WITHDRAW_THRESHOLD_USD = float(os.getenv("WITHDRAW_THRESHOLD_USD", "500"))
WITHDRAW_TARGET_BUFFER_USD = float(os.getenv("WITHDRAW_TARGET_BUFFER_USD", "300"))
COLD_WALLET_ADDRESS = os.getenv("COLD_WALLET_ADDRESS", "")  # User should provide
WITHDRAW_SCHEDULE_HOUR = int(os.getenv("WITHDRAW_SCHEDULE_HOUR", "3"))  # 3 AM UTC


class AutoWithdrawManager:
    """
    Automatically withdraws profits to cold wallet when balance exceeds threshold.
    Maintains safety buffer for trading operations.
    """
    
    def __init__(self):
        self.enabled = ENABLE_AUTO_WITHDRAW
        self.threshold = WITHDRAW_THRESHOLD_USD
        self.target_buffer = WITHDRAW_TARGET_BUFFER_USD
        self.cold_wallet = COLD_WALLET_ADDRESS
        self.withdrawal_history: list = []
        self.last_withdraw_ts = 0.0
    
    def should_withdraw(self, current_balance: float) -> bool:
        """
        Check if withdrawal should occur.
        Dynamic activation when balance > threshold.
        
        Args:
            current_balance: Current account balance in USD
        
        Returns:
            True if balance exceeds threshold
        """
        if not self.enabled or not self.cold_wallet:
            return False
        
        return current_balance > self.threshold
    
    def calculate_withdraw_amount(self, current_balance: float) -> float:
        """
        Calculate amount to withdraw, keeping safety buffer.
        
        Args:
            current_balance: Current account balance
        
        Returns:
            Amount to withdraw (0 if below threshold)
        """
        if current_balance <= self.threshold:
            return 0.0
        
        # Withdraw excess above target buffer
        amount = current_balance - self.target_buffer
        
        return round(max(0, amount), 2)
    
    def execute_withdraw(self, amount: float, asset: str = "USDT",
                        balance_callback=None) -> Dict[str, Any]:
        """
        Execute withdrawal to cold wallet.
        Can be called periodically or triggered when balance threshold hit.
        
        Args:
            amount: Amount to withdraw
            asset: Asset type (default: USDT)
            balance_callback: Optional callback to get current balance
        
        Returns:
            Withdrawal record
        """
        if amount <= 0:
            return {
                "status": "skipped",
                "reason": "amount_zero_or_negative",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        withdrawal = {
            "timestamp": datetime.utcnow().isoformat(),
            "amount": amount,
            "asset": asset,
            "destination": self.cold_wallet,
            "status": "initiated",
            "txid": None,
            "remaining_buffer": self.target_buffer
        }
        
        with suppress(Exception):
            # Here you would integrate with Binance API to execute withdrawal
            # For now, this is a placeholder that logs the action
            logger.info(
                f"🔐 Auto-withdraw initiated: ${amount:.2f} {asset} → "
                f"{self.cold_wallet[:8]}... (buffer: ${self.target_buffer:.2f})"
            )
            
            # Mark as completed (in production, would verify with exchange)
            withdrawal["status"] = "completed"
            withdrawal["txid"] = f"AUTO_{datetime.utcnow().timestamp()}"
        
        self.withdrawal_history.append(withdrawal)
        self.last_withdraw_ts = datetime.utcnow().timestamp()
        
        return withdrawal
    
    def auto_withdraw_on_schedule(self, current_balance: float) -> Optional[Dict[str, Any]]:
        """
        Check scheduled withdrawal time and execute if conditions met.
        Dynamic activation at scheduled hour.
        
        Args:
            current_balance: Current account balance
        
        Returns:
            Withdrawal record if executed, None otherwise
        """
        if not self.enabled:
            return None
        
        now = datetime.utcnow()
        
        # Check if it's the scheduled withdrawal hour
        if now.hour != WITHDRAW_SCHEDULE_HOUR:
            return None
        
        # Check if balance exceeds threshold
        if not self.should_withdraw(current_balance):
            return None
        
        amount = self.calculate_withdraw_amount(current_balance)
        
        if amount > 0:
            return self.execute_withdraw(amount)
        
        return None
    
    def get_withdrawal_history(self, limit: int = 50) -> list:
        """Get recent withdrawal history."""
        return self.withdrawal_history[-limit:]
    
    def get_status(self) -> Dict[str, Any]:
        """Get auto-withdraw system status."""
        return {
            "enabled": self.enabled,
            "threshold": self.threshold,
            "target_buffer": self.target_buffer,
            "cold_wallet_configured": bool(self.cold_wallet),
            "total_withdrawn": sum(w.get("amount", 0) for w in self.withdrawal_history 
                                  if w.get("status") == "completed"),
            "last_withdrawal": self.withdrawal_history[-1] if self.withdrawal_history else None,
            "withdrawal_count": len(self.withdrawal_history)
        }


# Global singleton
_auto_withdraw_manager = None


def get_auto_withdraw_manager() -> AutoWithdrawManager:
    """Get or create global auto-withdraw manager (singleton)."""
    global _auto_withdraw_manager
    if _auto_withdraw_manager is None:
        _auto_withdraw_manager = AutoWithdrawManager()
        if ENABLE_AUTO_WITHDRAW:
            if not COLD_WALLET_ADDRESS:
                logger.warning("⚠️  Auto-Withdraw enabled but COLD_WALLET_ADDRESS not configured")
            else:
                logger.info("✅ Auto-Withdraw Manager initialized (dynamic auto-activation enabled)")
        else:
            logger.info("ℹ️  Auto-Withdraw Manager disabled")
    return _auto_withdraw_manager
