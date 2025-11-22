#!/usr/bin/env python3
"""
Adaptive Budget Engine - Auto-scales ALL settings based on wallet balance
=========================================================================
MetaBrain v9.2.4 Feature: Dynamic Budget Allocation

Auto-detects available balance and scales:
- MIN_INVESTMENT_USD: Budget per trade ($10-$50 range)
- MIN_QUALITY_FLOOR: Quality threshold (3.0-5.5)
- MAX_LEVERAGE: Maximum leverage (5x-35x)
- Daily trade caps: Based on balance
- Symbol pool quality: Adapt symbol pool filtering

Philosophy:
- Small balance ($50-500): Use $10-15 per trade, leverage 5-8x, relaxed quality
- Medium balance ($500-1500): Use $15-25 per trade, leverage 8-15x, normal quality
- Large balance ($1500+): Use $25-50 per trade, leverage 15-35x, strict quality

This ensures the system auto-adapts to your current account state.
"""

import logging
import os
from typing import Dict, Any

try:
    from utils.binance_client import futures_account
    # Wrap it as async
    async def futures_account_safe(*args, **kwargs):
        return futures_account(*args, **kwargs)
except ImportError:
    # Fallback if not available
    async def futures_account_safe(*args, **kwargs):
        return None

logger = logging.getLogger("adaptive_budget_engine")


class AdaptiveBudgetEngine:
    """
    Detects account balance and auto-scales all trading parameters.
    Runs once per scan cycle, not per trade.
    """
    
    def __init__(self):
        self.logger = logger
        self.last_balance = None
        self.last_config = {}
        
    async def detect_and_scale(self) -> Dict[str, Any]:
        """
        Detect current balance from Binance and return scaled configuration.
        
        Returns:
        {
            'balance_usdt': float,
            'min_investment_usd': float,
            'min_quality_floor': float,
            'max_leverage': float,
            'daily_trade_cap': int,
            'symbol_pool_quality_floor': float,
            'confidence': str  # 'HIGH', 'MEDIUM', 'LOW'
        }
        """
        try:
            # Get current balance from Binance
            balance_response = await futures_account_safe()
            
            if not balance_response or not balance_response.get('totalWalletBalance'):
                self.logger.warning("❌ Could not detect balance from Binance, using env defaults")
                return self._get_env_defaults()
            
            balance_usdt = float(balance_response['totalWalletBalance'])
            self.logger.info(f"💰 Detected balance: ${balance_usdt:.2f} USDT")
            
            # Scale based on balance
            config = self._calculate_scaling(balance_usdt)
            
            self.last_balance = balance_usdt
            self.last_config = config
            
            return config
            
        except Exception as e:
            self.logger.error(f"⚠️ Error detecting balance: {e}")
            return self._get_env_defaults()
    
    def _calculate_scaling(self, balance: float) -> Dict[str, Any]:
        """
        Calculate scaled configuration based on balance.
        
        Budget Tiers:
        - Tier 1: $50-200 USDT → Conservative
        - Tier 2: $200-500 USDT → Normal
        - Tier 3: $500-1500 USDT → Moderate
        - Tier 4: $1500+ USDT → Aggressive
        """
        
        if balance < 50:
            # Micro account: barely tradeable
            min_investment = 5.0
            min_quality = 6.5
            max_leverage = 5.0
            daily_cap = 1
            pool_quality = 6.0
            confidence = "LOW"
            msg = "⚠️ MICRO: Account < $50 USDT - extreme caution"
            
        elif balance < 200:
            # Tiny account: very careful
            min_investment = 10.0
            min_quality = 5.5
            max_leverage = 8.0
            daily_cap = 2
            pool_quality = 5.0
            confidence = "LOW"
            msg = "🔴 TINY: Account $50-200 - use small trades"
            
        elif balance < 500:
            # Small account: cautious
            min_investment = 15.0
            min_quality = 5.0
            max_leverage = 10.0
            daily_cap = 3
            pool_quality = 4.5
            confidence = "MEDIUM"
            msg = "🟡 SMALL: Account $200-500 - normal quality filter"
            
        elif balance < 1000:
            # Medium account: normal
            min_investment = 20.0
            min_quality = 4.5
            max_leverage = 15.0
            daily_cap = 5
            pool_quality = 4.0
            confidence = "MEDIUM"
            msg = "🟢 MEDIUM: Account $500-1000 - normal operation"
            
        elif balance < 2000:
            # Large account: confident
            min_investment = 30.0
            min_quality = 4.0
            max_leverage = 25.0
            daily_cap = 7
            pool_quality = 3.5
            confidence = "HIGH"
            msg = "🟢 LARGE: Account $1000-2000 - active trading"
            
        else:
            # Very large account: aggressive
            min_investment = 50.0
            min_quality = 3.5
            max_leverage = 35.0
            daily_cap = 10
            pool_quality = 3.0
            confidence = "HIGH"
            msg = "🟢 WHALE: Account $2000+ - full automation"
        
        self.logger.info(msg)
        
        return {
            'balance_usdt': balance,
            'min_investment_usd': min_investment,
            'min_quality_floor': min_quality,
            'max_leverage': max_leverage,
            'daily_trade_cap': daily_cap,
            'symbol_pool_quality_floor': pool_quality,
            'confidence': confidence
        }
    
    def _get_env_defaults(self) -> Dict[str, Any]:
        """Return defaults from environment variables."""
        return {
            'balance_usdt': 0.0,
            'min_investment_usd': float(os.getenv('MIN_INVESTMENT_USD', '15.0')),
            'min_quality_floor': float(os.getenv('MIN_QUALITY_FLOOR', '5.5')),
            'max_leverage': 35.0,
            'daily_trade_cap': 10,
            'symbol_pool_quality_floor': 4.0,
            'confidence': 'UNKNOWN'
        }


# Singleton instance
_engine = None


def get_adaptive_budget_engine() -> AdaptiveBudgetEngine:
    """Get or create singleton engine."""
    global _engine
    if _engine is None:
        _engine = AdaptiveBudgetEngine()
    return _engine


async def get_adaptive_config() -> Dict[str, Any]:
    """
    Get current adaptive configuration based on balance.
    
    Call this once per scan cycle, not per trade!
    """
    engine = get_adaptive_budget_engine()
    return await engine.detect_and_scale()
