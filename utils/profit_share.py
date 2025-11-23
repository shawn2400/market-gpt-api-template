# -*- coding: utf-8 -*-
"""
ULTRA-PLUS: Profit-Share System - Automatic 18% profit billing.
Dynamic auto-activation on Sundays for weekly billing.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable
from contextlib import suppress

logger = logging.getLogger(__name__)

# Dynamic config
ENABLE_PROFIT_SHARE = os.getenv("ENABLE_PROFIT_SHARE", "1") == "1"
PROFIT_SHARE_RATE = float(os.getenv("PROFIT_SHARE_RATE", "0.18"))  # 18%
BILLING_DAY = int(os.getenv("BILLING_DAY", "6"))  # 6 = Sunday
BILLING_HOUR = int(os.getenv("BILLING_HOUR", "23"))  # 23:00 UTC


class ProfitShareManager:
    """
    Manages automatic profit-share billing (18% of weekly profits).
    Dynamic auto-activation for multi-user systems.
    """
    
    def __init__(self):
        self.enabled = ENABLE_PROFIT_SHARE
        self.profit_share_rate = PROFIT_SHARE_RATE
        self.billing_history: Dict[str, list] = {}  # user_id -> list of billing events
        self.pending_payments: Dict[str, Dict] = {}  # user_id -> {amount, since_ts}
    
    def calculate_share(self, weekly_pnl: float) -> float:
        """
        Calculate profit share amount from weekly PnL.
        Only charges on positive PnL.
        
        Args:
            weekly_pnl: Weekly profit/loss in USD
        
        Returns:
            Amount to charge (0 if no profit)
        """
        if weekly_pnl <= 0:
            return 0.0
        
        return round(weekly_pnl * self.profit_share_rate, 2)
    
    def create_billing(self, user_id: str, weekly_pnl: float, 
                      email: Optional[str] = None) -> Dict[str, Any]:
        """
        Create billing invoice for a user based on weekly PnL.
        Dynamic activation on profitable weeks.
        
        Args:
            user_id: User identifier
            weekly_pnl: Weekly profit/loss
            email: Optional user email for notifications
        
        Returns:
            Billing record
        """
        if not self.enabled or weekly_pnl <= 0:
            return {"status": "no_charge", "reason": "negative_or_zero_pnl"}
        
        amount = self.calculate_share(weekly_pnl)
        
        billing = {
            "user_id": user_id,
            "week_of": datetime.utcnow().isoformat(),
            "weekly_pnl": round(weekly_pnl, 2),
            "share_rate": self.profit_share_rate,
            "amount_due": amount,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "due_date": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "email": email,
            "paid_at": None
        }
        
        # Track in history
        if user_id not in self.billing_history:
            self.billing_history[user_id] = []
        self.billing_history[user_id].append(billing)
        
        # Track as pending payment
        if user_id not in self.pending_payments:
            self.pending_payments[user_id] = {
                "amount": 0.0,
                "invoices": []
            }
        self.pending_payments[user_id]["amount"] += amount
        self.pending_payments[user_id]["invoices"].append(billing)
        
        logger.info(f"💰 Billing created for {user_id}: ${amount:.2f} (from ${weekly_pnl:.2f} profit)")
        
        return billing
    
    def mark_paid(self, user_id: str, invoice_id: str = None) -> bool:
        """
        Mark a billing as paid.
        
        Args:
            user_id: User identifier
            invoice_id: Optional specific invoice to mark paid
        
        Returns:
            True if marked successfully
        """
        if user_id not in self.pending_payments:
            return False
        
        with suppress(Exception):
            # Mark all pending payments as paid
            for invoice in self.pending_payments[user_id].get("invoices", []):
                if invoice["status"] == "pending":
                    invoice["status"] = "paid"
                    invoice["paid_at"] = datetime.utcnow().isoformat()
            
            self.pending_payments[user_id]["amount"] = 0.0
            logger.info(f"✅ Payment marked for {user_id}")
            return True
        
        return False
    
    def get_pending(self, user_id: str) -> Dict[str, Any]:
        """Get pending payment info for user."""
        if user_id not in self.pending_payments:
            return {"user_id": user_id, "amount_due": 0.0, "invoices": []}
        
        return {
            "user_id": user_id,
            "amount_due": self.pending_payments[user_id]["amount"],
            "invoices": self.pending_payments[user_id]["invoices"]
        }
    
    def get_billing_history(self, user_id: str) -> list:
        """Get all billing history for a user."""
        return self.billing_history.get(user_id, [])
    
    def should_bill(self) -> bool:
        """
        Check if it's time to run weekly billing (Sundays at billing hour).
        Dynamic auto-activation.
        
        Returns:
            True if billing should run now
        """
        if not self.enabled:
            return False
        
        now = datetime.utcnow()
        return now.weekday() == BILLING_DAY and now.hour == BILLING_HOUR
    
    def generate_invoice_message(self, billing: Dict[str, Any]) -> str:
        """Generate user-friendly invoice message."""
        return f"""
💰 **Weekly Profit-Share Invoice**

User: {billing['user_id']}
Period: Week of {billing['week_of'][:10]}
Weekly PNL: ${billing['weekly_pnl']:.2f}
Your Share (18%): ${billing['amount_due']:.2f}

Due Date: {billing['due_date'][:10]}

Please pay via USDT to confirm billing.
Failure to pay within 24h will trigger auto-suspension.

Invoice Date: {billing['created_at']}
"""


# Global singleton
_profit_share_manager = None


def get_profit_share_manager() -> ProfitShareManager:
    """Get or create global profit-share manager (singleton)."""
    global _profit_share_manager
    if _profit_share_manager is None:
        _profit_share_manager = ProfitShareManager()
        if ENABLE_PROFIT_SHARE:
            logger.info("✅ Profit-Share Manager initialized (18% billing enabled)")
        else:
            logger.info("ℹ️  Profit-Share Manager disabled")
    return _profit_share_manager
