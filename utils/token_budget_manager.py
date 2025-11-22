#!/usr/bin/env python3
"""
Token Budget Manager - Smart AI Brain Suspension/Resume System
==============================================================
Intelligently suspends AI brains when balance insufficient.
Auto-resumes when cash available. Protects AI quality.

תקציב של סוכנים חכם:
- ברגע שאין כסף → כל הסוכנים suspend
- ברגע שניכנס כסף → סוכנים עולים בחוכמה (מזול ל-יקר)
"""

import logging
import os
import json
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger("algogpt.token_budget")

# Brain cost matrix ($ per call)
BRAIN_COSTS = {
    "deepseek": 0.0001,      # Ultra-cheap
    "qwen": 0.0,             # FREE!
    "gemini": 0.00005,       # Very cheap
    "claude": 0.003,         # Mid-cost
    "grok": 0.0008,          # Mid-cost
    "gpt4o_mini": 0.0005,    # Cheap
}

# Brain priority (cheaper = higher priority when activating)
BRAIN_PRIORITY = {
    "qwen": 1,       # Free - always first
    "deepseek": 2,   # Cheapest paid
    "gemini": 3,     # Very cheap
    "gpt4o_mini": 4, # Cheap
    "grok": 5,       # Mid
    "claude": 6,     # Most expensive
}

@dataclass
class BrainBudget:
    """Track budget & suspension status for each brain."""
    name: str
    cost_per_call: float
    priority: int
    enabled: bool = True
    suspended: bool = False
    suspension_reason: str = ""
    calls_made: int = 0
    total_cost: float = 0.0
    last_call_time: float = field(default_factory=time.time)
    resume_threshold: float = 10.0  # Resume when balance > $10
    
    def should_suspend(self, available_balance: float) -> bool:
        """Check if brain should be suspended."""
        # Never suspend FREE brain (Qwen)
        if self.cost_per_call == 0.0:
            return False
        # Suspend if balance too low
        return available_balance < 5.0
    
    def should_resume(self, available_balance: float) -> bool:
        """Check if brain should be resumed."""
        if not self.suspended:
            return False
        # Resume when balance > resume_threshold
        return available_balance >= self.resume_threshold


class TokenBudgetManager:
    """Manage AI brain budgets intelligently."""
    
    def __init__(self, redis_conn=None):
        self.redis = redis_conn
        self.brains: Dict[str, BrainBudget] = self._init_brains()
        self.last_balance = 0.0
        self.total_cycle_budget = 0.0
        self.calls_in_cycle = 0
        self.logger = logger
    
    def _init_brains(self) -> Dict[str, BrainBudget]:
        """Initialize all brain budgets."""
        brains = {}
        for brain_name, cost in BRAIN_COSTS.items():
            priority = BRAIN_PRIORITY.get(brain_name, 999)
            brains[brain_name] = BrainBudget(
                name=brain_name,
                cost_per_call=cost,
                priority=priority,
                enabled=self._check_brain_enabled(brain_name)
            )
        return brains
    
    def _check_brain_enabled(self, brain_name: str) -> bool:
        """Check if brain is enabled by env vars."""
        enable_map = {
            "deepseek": "ENABLE_DEEPSEEK",
            "qwen": "ENABLE_QWEN",
            "gemini": "ENABLE_GEMINI",
            "claude": "ENABLE_ANTHROPIC",
            "grok": "ENABLE_XAI",
            "gpt4o_mini": "ENABLE_OPENAI",
        }
        env_var = enable_map.get(brain_name, "")
        if not env_var:
            return False
        return os.getenv(env_var, "0").strip().lower() in ("1", "true", "yes")
    
    def sync_balance(self, available_balance: float):
        """Update wallet balance & re-evaluate brain suspensions."""
        self.last_balance = available_balance
        
        balance_changed = True
        for brain_name, brain in self.brains.items():
            if not brain.enabled:
                continue
            
            # Check if should suspend
            if not brain.suspended and brain.should_suspend(available_balance):
                brain.suspended = True
                brain.suspension_reason = f"Balance ${available_balance:.2f} < $5.0"
                self.logger.warning(
                    f"🔴 {brain_name.upper()} SUSPENDED: {brain.suspension_reason}"
                )
            
            # Check if should resume
            elif brain.suspended and brain.should_resume(available_balance):
                brain.suspended = False
                brain.suspension_reason = ""
                self.logger.info(
                    f"🟢 {brain_name.upper()} RESUMED: Balance ${available_balance:.2f} >= ${brain.resume_threshold:.2f}"
                )
    
    def get_active_brains(self) -> List[str]:
        """Get list of active (non-suspended) brains, sorted by priority."""
        active = [
            name for name, brain in self.brains.items()
            if brain.enabled and not brain.suspended
        ]
        # Sort by priority (lower = higher priority)
        active.sort(key=lambda x: self.brains[x].priority)
        return active
    
    def get_brain_status(self) -> Dict[str, Any]:
        """Get status of all brains."""
        status = {}
        for brain_name, brain in self.brains.items():
            status[brain_name] = {
                "enabled": brain.enabled,
                "suspended": brain.suspended,
                "cost_per_call": brain.cost_per_call,
                "calls_made": brain.calls_made,
                "total_cost": round(brain.total_cost, 6),
                "suspension_reason": brain.suspension_reason,
            }
        return status
    
    def record_call(self, brain_name: str, success: bool = True) -> bool:
        """Record a brain call for budget tracking."""
        if brain_name not in self.brains:
            self.logger.warning(f"⚠️ Unknown brain: {brain_name}")
            return False
        
        brain = self.brains[brain_name]
        if brain.suspended:
            self.logger.warning(f"⚠️ {brain_name} is SUSPENDED, skipping call")
            return False
        
        if success:
            brain.calls_made += 1
            brain.total_cost += brain.cost_per_call
            brain.last_call_time = time.time()
            self.calls_in_cycle += 1
            self.total_cycle_budget += brain.cost_per_call
        
        return True
    
    def get_cycle_cost(self) -> float:
        """Get total cost for current cycle."""
        return round(self.total_cycle_budget, 6)
    
    def reset_cycle(self):
        """Reset cycle counters."""
        self.calls_in_cycle = 0
        self.total_cycle_budget = 0.0
    
    def get_daily_cost(self) -> float:
        """Get total cost for all brains today."""
        total = 0.0
        for brain in self.brains.values():
            total += brain.total_cost
        return round(total, 6)
    
    def get_affordability_score(self) -> float:
        """
        Score how healthy the token budget is (0-100).
        100 = plenty of budget, 0 = no budget.
        """
        if self.last_balance <= 5.0:
            return 0.0
        if self.last_balance >= 50.0:
            return 100.0
        
        # Scale linearly from 5 to 50
        return (self.last_balance - 5.0) / (50.0 - 5.0) * 100.0
    
    def get_summary(self) -> Dict[str, Any]:
        """Get comprehensive budget summary."""
        active_brains = self.get_active_brains()
        
        return {
            "balance": round(self.last_balance, 2),
            "affordability_score": round(self.get_affordability_score(), 1),
            "active_brains": active_brains,
            "active_count": len(active_brains),
            "total_brains": len([b for b in self.brains.values() if b.enabled]),
            "cycle_cost": self.get_cycle_cost(),
            "daily_cost": self.get_daily_cost(),
            "brain_status": self.get_brain_status(),
        }


# Global instance
_manager: Optional[TokenBudgetManager] = None


def get_token_budget_manager(redis_conn=None) -> TokenBudgetManager:
    """Get or create token budget manager."""
    global _manager
    if _manager is None:
        _manager = TokenBudgetManager(redis_conn=redis_conn)
    return _manager


__all__ = [
    "TokenBudgetManager",
    "get_token_budget_manager",
    "BRAIN_COSTS",
    "BRAIN_PRIORITY",
]
