#!/usr/bin/env python3
# utils/cost_tracker.py
"""
💰 AI Cost Tracking System
Tracks AI API usage and costs in real-time
Provides daily reports via Telegram
"""
import os
import logging
import time
from typing import Dict, Any, List
from dataclasses import dataclass, asdict
import json

logger = logging.getLogger("algogpt.cost_tracker")

# Cost per 1M tokens (USD)
COSTS_PER_1M_TOKENS = {
    "gpt-4o-mini": 0.150,  # $0.15 per 1M tokens (input)
    "gpt-5": 15.00,  # $15 per 1M tokens (expensive!)
    "deepseek-chat": 0.14,  # $0.14 per 1M tokens (cheap!)
    "grok-2": 2.00,  # $2 per 1M tokens
    "gemini-2.0-flash": 0.075,  # $0.075 per 1M tokens (free tier)
    "claude-sonnet-3.5": 3.00,  # $3 per 1M tokens
}

@dataclass
class AICall:
    """Single AI API call record"""
    timestamp: float
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    symbol: str = ""
    purpose: str = ""  # "consensus", "review", "proposal"


class CostTracker:
    """
    Tracks AI API costs in real-time
    Saves daily totals to file for persistence
    """
    
    def __init__(self):
        self.calls: List[AICall] = []
        self.daily_total = 0.0
        self.cycle_total = 0.0
        self.last_reset = time.time()
        
        # Load previous day's data if exists
        self.load_state()
    
    def track_call(
        self,
        provider: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        symbol: str = "",
        purpose: str = ""
    ) -> float:
        """
        Track a single AI API call and return cost
        
        Returns: cost in USD
        """
        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens
        
        # Calculate cost
        cost_per_token = COSTS_PER_1M_TOKENS.get(model, 1.0) / 1_000_000
        cost_usd = total_tokens * cost_per_token
        
        # Create record
        call = AICall(
            timestamp=time.time(),
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            symbol=symbol,
            purpose=purpose
        )
        
        self.calls.append(call)
        self.daily_total += cost_usd
        self.cycle_total += cost_usd
        
        logger.info(
            f"💰 AI Cost: {provider}/{model} → ${cost_usd:.4f} "
            f"({total_tokens:,} tokens) | Cycle: ${self.cycle_total:.3f} | Daily: ${self.daily_total:.3f}"
        )
        
        return cost_usd
    
    def reset_cycle(self) -> float:
        """Reset cycle counter and return cycle cost"""
        cycle_cost = self.cycle_total
        self.cycle_total = 0.0
        return cycle_cost
    
    def reset_daily(self) -> float:
        """Reset daily counter and return daily cost"""
        daily_cost = self.daily_total
        self.daily_total = 0.0
        self.last_reset = time.time()
        self.calls = []  # Clear history
        self.save_state()
        return daily_cost
    
    def get_daily_summary(self) -> Dict[str, Any]:
        """Get daily cost summary"""
        if not self.calls:
            return {
                "total_cost": 0.0,
                "total_calls": 0,
                "total_tokens": 0,
                "by_provider": {},
                "by_model": {}
            }
        
        by_provider: Dict[str, Dict[str, Any]] = {}
        by_model: Dict[str, Dict[str, Any]] = {}
        
        for call in self.calls:
            # By provider
            if call.provider not in by_provider:
                by_provider[call.provider] = {"calls": 0, "tokens": 0, "cost": 0.0}
            by_provider[call.provider]["calls"] += 1
            by_provider[call.provider]["tokens"] += call.total_tokens
            by_provider[call.provider]["cost"] += call.cost_usd
            
            # By model
            if call.model not in by_model:
                by_model[call.model] = {"calls": 0, "tokens": 0, "cost": 0.0}
            by_model[call.model]["calls"] += 1
            by_model[call.model]["tokens"] += call.total_tokens
            by_model[call.model]["cost"] += call.cost_usd
        
        return {
            "total_cost": self.daily_total,
            "total_calls": len(self.calls),
            "total_tokens": sum(c.total_tokens for c in self.calls),
            "by_provider": by_provider,
            "by_model": by_model
        }
    
    def save_state(self):
        """Save state to file for persistence"""
        try:
            state = {
                "daily_total": self.daily_total,
                "cycle_total": self.cycle_total,
                "last_reset": self.last_reset,
                "calls_count": len(self.calls)
            }
            
            state_file = "/tmp/cost_tracker_state.json"
            with open(state_file, "w") as f:
                json.dump(state, f)
            
            logger.debug(f"Cost tracker state saved: ${self.daily_total:.3f}")
        except Exception as e:
            logger.warning(f"Failed to save cost tracker state: {e}")
    
    def load_state(self):
        """Load state from file"""
        try:
            state_file = "/tmp/cost_tracker_state.json"
            if not os.path.exists(state_file):
                return
            
            with open(state_file, "r") as f:
                state = json.load(f)
            
            self.daily_total = state.get("daily_total", 0.0)
            self.cycle_total = state.get("cycle_total", 0.0)
            self.last_reset = state.get("last_reset", time.time())
            
            logger.info(f"Cost tracker state loaded: ${self.daily_total:.3f} daily")
        except Exception as e:
            logger.warning(f"Failed to load cost tracker state: {e}")


# Global instance
_cost_tracker: CostTracker = None


def get_cost_tracker() -> CostTracker:
    """Get or create global cost tracker"""
    global _cost_tracker
    if _cost_tracker is None:
        _cost_tracker = CostTracker()
    return _cost_tracker


def track_ai_call(
    provider: str,
    model: str,
    tokens: int = 0,
    symbol: str = "",
    purpose: str = ""
) -> float:
    """
    Convenience function to track AI call
    
    Returns: cost in USD
    """
    tracker = get_cost_tracker()
    return tracker.track_call(
        provider=provider,
        model=model,
        total_tokens=tokens,
        symbol=symbol,
        purpose=purpose
    )


__all__ = ["CostTracker", "get_cost_tracker", "track_ai_call"]
