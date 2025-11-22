"""
💰 QUANTUM TOKEN MANAGER - Smart Budget & Cost Control System
Performance-based token allocation across 7 council members
"""

import logging
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)

class QuantumTokenManager:
    """Manages token budget across council members based on performance"""
    
    def __init__(self, monthly_budget: float = 100.0):
        self.monthly_budget = monthly_budget
        self.start_date = datetime.now()
        
        # Agent budgets with performance tracking
        self.agent_budgets = {
            'deepseek': {
                'allocated': 35,
                'used': 0.0,
                'performance_score': 1.0,
                'decision_count': 0
            },
            'grok': {
                'allocated': 25,
                'used': 0.0,
                'performance_score': 1.0,
                'decision_count': 0
            },
            'claude': {
                'allocated': 20,
                'used': 0.0,
                'performance_score': 1.0,
                'decision_count': 0
            },
            'qwen': {
                'allocated': 10,
                'used': 0.0,
                'performance_score': 1.0,
                'decision_count': 0
            },
            'gemini': {
                'allocated': 5,
                'used': 0.0,
                'performance_score': 1.0,
                'decision_count': 0
            },
            'falcon': {
                'allocated': 3,
                'used': 0.0,
                'performance_score': 1.0,
                'decision_count': 0
            },
            'mixtral': {
                'allocated': 2,
                'used': 0.0,
                'performance_score': 1.0,
                'decision_count': 0
            }
        }
        
        self.usage_history = []
    
    def can_use_agent(self, agent: str, task_importance: float = 0.5) -> bool:
        """
        Check if agent can be used based on:
        - Remaining budget
        - Task importance (0.0-1.0)
        - Agent performance score
        """
        
        if agent not in self.agent_budgets:
            logger.warning(f"⚠️ Unknown agent: {agent}")
            return False
        
        budget = self.agent_budgets[agent]
        remaining = budget['allocated'] - budget['used']
        
        # Cost-benefit analysis
        performance = budget['performance_score']
        cost_benefit_ratio = task_importance * performance
        
        # Only approve if cost-justified
        can_afford = remaining > 0
        is_justified = cost_benefit_ratio >= 0.6
        
        return can_afford and is_justified
    
    def estimate_task_cost(self, agent: str, task_complexity: float) -> float:
        """Estimate cost of task based on agent and complexity"""
        
        agent_cost_multiplier = {
            'deepseek': 5.0,
            'grok': 3.0,
            'claude': 4.0,
            'qwen': 1.5,
            'gemini': 2.0,
            'falcon': 2.5,
            'mixtral': 0.5
        }
        
        base_cost = agent_cost_multiplier.get(agent, 1.0)
        estimated_cost = base_cost * task_complexity
        
        return estimated_cost
    
    def record_usage(self, agent: str, tokens_used: float, task_type: str = 'unknown'):
        """Record token usage for an agent"""
        
        if agent not in self.agent_budgets:
            logger.warning(f"⚠️ Recording usage for unknown agent: {agent}")
            return
        
        self.agent_budgets[agent]['used'] += tokens_used
        self.agent_budgets[agent]['decision_count'] += 1
        
        # Log usage
        usage_record = {
            'timestamp': datetime.now().isoformat(),
            'agent': agent,
            'tokens': tokens_used,
            'task_type': task_type,
            'remaining': self.agent_budgets[agent]['allocated'] - self.agent_budgets[agent]['used']
        }
        
        self.usage_history.append(usage_record)
        
        logger.debug(f"💸 {agent.upper()}: used {tokens_used:.2f} tokens | task={task_type}")
    
    def update_performance_scores(self, trade_results: Dict[str, Any]):
        """Update agent performance scores based on trade results"""
        
        for agent, budget in self.agent_budgets.items():
            if budget['decision_count'] == 0:
                continue
            
            # Simulate win rate from trade results
            profitable_count = sum(1 for t in trade_results.get('trades', []) 
                                  if t.get('profitable', False))
            total_trades = len(trade_results.get('trades', []))
            
            if total_trades > 0:
                win_rate = profitable_count / total_trades
                # Performance score: 0.5-1.5 (1.0 = baseline)
                budget['performance_score'] = 0.5 + min(win_rate, 1.0)
            
            logger.debug(f"📊 {agent.upper()}: performance_score={budget['performance_score']:.2f}")
    
    def reallocate_budgets_by_performance(self):
        """Dynamically reallocate budgets based on recent performance"""
        
        logger.info("🔄 REALLOCATING BUDGETS BY PERFORMANCE...")
        
        # Calculate total performance
        total_performance = sum(b['performance_score'] for b in self.agent_budgets.values())
        
        if total_performance == 0:
            total_performance = len(self.agent_budgets)
        
        # Reallocate proportionally
        for agent, budget in self.agent_budgets.items():
            performance_ratio = budget['performance_score'] / total_performance
            new_allocation = self.monthly_budget * performance_ratio
            old_allocation = budget['allocated']
            
            budget['allocated'] = new_allocation
            
            if abs(new_allocation - old_allocation) > 0.1:
                logger.info(f"   📈 {agent.upper()}: ${old_allocation:.2f} → ${new_allocation:.2f}")
    
    def get_budget_status(self) -> Dict[str, Any]:
        """Get current budget status"""
        
        total_allocated = sum(b['allocated'] for b in self.agent_budgets.values())
        total_used = sum(b['used'] for b in self.agent_budgets.values())
        total_remaining = total_allocated - total_used
        
        status = {
            'timestamp': datetime.now().isoformat(),
            'total_budget': self.monthly_budget,
            'total_allocated': total_allocated,
            'total_used': total_used,
            'total_remaining': total_remaining,
            'usage_percent': (total_used / total_allocated * 100) if total_allocated > 0 else 0,
            'agents': {}
        }
        
        for agent, budget in self.agent_budgets.items():
            remaining = budget['allocated'] - budget['used']
            status['agents'][agent] = {
                'allocated': budget['allocated'],
                'used': budget['used'],
                'remaining': remaining,
                'remaining_percent': (remaining / budget['allocated'] * 100) if budget['allocated'] > 0 else 0,
                'performance_score': budget['performance_score'],
                'decisions': budget['decision_count']
            }
        
        return status
    
    def should_alert_budget_limit(self) -> bool:
        """Check if approaching budget limit"""
        
        total_used = sum(b['used'] for b in self.agent_budgets.values())
        usage_percent = total_used / self.monthly_budget if self.monthly_budget > 0 else 0
        
        # Alert if >80% used
        return usage_percent > 0.8
    
    def log_budget_summary(self):
        """Log current budget summary"""
        
        status = self.get_budget_status()
        
        logger.info(f"💰 TOKEN BUDGET SUMMARY:")
        logger.info(f"   📊 Total: ${status['total_used']:.2f} / ${status['total_allocated']:.2f} ({status['usage_percent']:.1f}%)")
        logger.info(f"   ⏳ Remaining: ${status['total_remaining']:.2f}")
        
        # Warn if low
        if self.should_alert_budget_limit():
            logger.warning(f"⚠️ WARNING: Budget usage >80%!")


# Singleton instance
_token_manager = None

def get_token_manager(monthly_budget: float = 100.0) -> QuantumTokenManager:
    """Get or create token manager singleton"""
    global _token_manager
    if _token_manager is None:
        _token_manager = QuantumTokenManager(monthly_budget)
        logger.info("✅ Quantum Token Manager initialized")
    return _token_manager
