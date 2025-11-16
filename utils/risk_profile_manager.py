# -*- coding: utf-8 -*-
# utils/risk_profile_manager.py
"""
Balance-Tiered Risk Profile System
Auto-adjusts trading parameters based on account size
"""
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("algogpt.risk_profile")

@dataclass
class RiskProfile:
    """Risk profile configuration for a given account balance tier"""
    name: str
    min_balance: float
    max_balance: float
    max_positions: int
    position_size_percent: float  # 0.08 = 8%
    max_leverage: int
    daily_risk_limit: float  # 0.05 = 5%
    max_risk_per_trade: float  # 0.10 = 10%
    
    def __repr__(self):
        return (
            f"RiskProfile({self.name}: ${self.min_balance:,.0f}-${self.max_balance:,.0f}, "
            f"positions={self.max_positions}, size={self.position_size_percent*100:.0f}%, "
            f"leverage={self.max_leverage}x)"
        )


# Define risk profile tiers (from conservative to aggressive)
RISK_PROFILES = [
    RiskProfile(
        name="MICRO",
        min_balance=0,
        max_balance=500,
        max_positions=3,
        position_size_percent=0.20,  # 20% - larger % but smaller absolute value
        max_leverage=3,
        daily_risk_limit=0.03,  # 3%
        max_risk_per_trade=0.05  # 5%
    ),
    RiskProfile(
        name="CONSERVATIVE",
        min_balance=500,
        max_balance=1000,
        max_positions=4,
        position_size_percent=0.15,  # 15%
        max_leverage=4,
        daily_risk_limit=0.04,  # 4%
        max_risk_per_trade=0.06  # 6%
    ),
    RiskProfile(
        name="BALANCED",
        min_balance=1000,
        max_balance=5000,
        max_positions=6,
        position_size_percent=0.12,  # 12%
        max_leverage=5,
        daily_risk_limit=0.05,  # 5%
        max_risk_per_trade=0.08  # 8%
    ),
    RiskProfile(
        name="GROWTH",
        min_balance=5000,
        max_balance=10000,
        max_positions=8,
        position_size_percent=0.10,  # 10%
        max_leverage=6,
        daily_risk_limit=0.06,  # 6%
        max_risk_per_trade=0.10  # 10%
    ),
    RiskProfile(
        name="AGGRESSIVE",
        min_balance=10000,
        max_balance=float('inf'),
        max_positions=10,
        position_size_percent=0.08,  # 8% - smaller % but larger absolute value
        max_leverage=8,
        daily_risk_limit=0.07,  # 7%
        max_risk_per_trade=0.10  # 10%
    )
]


class RiskProfileManager:
    """
    Manages risk profiles based on account balance.
    Auto-adjusts trading parameters as balance grows/shrinks.
    """
    
    def __init__(self):
        self.current_profile: Optional[RiskProfile] = None
        self.last_balance: Optional[float] = None
        logger.info(f"🎯 Risk Profile Manager initialized with {len(RISK_PROFILES)} tiers")
    
    def get_profile(self, balance: float) -> RiskProfile:
        """
        Get risk profile for given balance.
        
        Args:
            balance: Account balance in USDT
            
        Returns:
            RiskProfile matching the balance tier
        """
        # Find matching tier
        for profile in RISK_PROFILES:
            if profile.min_balance <= balance < profile.max_balance:
                # Log tier change
                if self.current_profile and self.current_profile.name != profile.name:
                    logger.info(
                        f"🔄 Risk Profile changed: {self.current_profile.name} → {profile.name} "
                        f"(balance: ${self.last_balance:,.2f} → ${balance:,.2f})"
                    )
                elif not self.current_profile:
                    logger.info(f"🎯 Initial Risk Profile: {profile.name} (balance: ${balance:,.2f})")
                
                self.current_profile = profile
                self.last_balance = balance
                return profile
        
        # Fallback to highest tier
        profile = RISK_PROFILES[-1]
        self.current_profile = profile
        self.last_balance = balance
        return profile
    
    def get_max_positions(self, balance: float) -> int:
        """Get maximum concurrent positions for balance"""
        profile = self.get_profile(balance)
        return profile.max_positions
    
    def get_position_size_percent(self, balance: float) -> float:
        """Get position size as percentage of balance (0.0-1.0)"""
        profile = self.get_profile(balance)
        return profile.position_size_percent
    
    def get_max_leverage(self, balance: float) -> int:
        """Get maximum leverage for balance"""
        profile = self.get_profile(balance)
        return profile.max_leverage
    
    def get_daily_risk_limit(self, balance: float) -> float:
        """Get daily risk limit as percentage (0.0-1.0)"""
        profile = self.get_profile(balance)
        return profile.daily_risk_limit
    
    def get_max_risk_per_trade(self, balance: float) -> float:
        """Get maximum risk per trade as percentage (0.0-1.0)"""
        profile = self.get_profile(balance)
        return profile.max_risk_per_trade
    
    def calculate_position_size(self, balance: float, leverage: int = 1) -> Dict[str, float]:
        """
        Calculate position size for given balance and leverage.
        
        Args:
            balance: Account balance in USDT
            leverage: Leverage to apply (1-35x)
            
        Returns:
            Dict with base_size, leveraged_size, and risk metrics
        """
        profile = self.get_profile(balance)
        
        # Base position size (before leverage)
        base_size = balance * profile.position_size_percent
        
        # Apply leverage cap from profile
        capped_leverage = min(leverage, profile.max_leverage)
        
        # Leveraged position size
        leveraged_size = base_size * capped_leverage
        
        # Max loss (if SL hits)
        max_loss = base_size * profile.max_risk_per_trade
        
        return {
            "base_size": base_size,
            "leveraged_size": leveraged_size,
            "leverage": capped_leverage,
            "max_loss": max_loss,
            "risk_percent": profile.max_risk_per_trade * 100,
            "profile": profile.name
        }
    
    def adjust_for_performance(self, balance: float, win_rate: float, profit_ratio: float) -> Dict[str, Any]:
        """
        Adjust parameters based on performance (like DynamicTradingAgent.update_dynamic_parameters).
        
        Args:
            balance: Current balance
            win_rate: Win rate (0.0-1.0)
            profit_ratio: Current balance / initial balance
            
        Returns:
            Adjusted parameters
        """
        profile = self.get_profile(balance)
        
        # Base parameters from profile
        adjusted_position_size = profile.position_size_percent
        adjusted_max_positions = profile.max_positions
        
        # Performance-based adjustments
        if profit_ratio > 1.2:  # 20%+ profit
            adjusted_position_size *= 1.2
            logger.info(f"📈 Increasing position size by 20% due to good performance (profit: {(profit_ratio-1)*100:.1f}%)")
        elif profit_ratio < 0.9:  # 10%+ loss
            adjusted_position_size *= 0.8
            adjusted_max_positions = max(2, int(adjusted_max_positions * 0.8))
            logger.info(f"📉 Reducing position size by 20% due to drawdown (loss: {(1-profit_ratio)*100:.1f}%)")
        
        # Additional caps for small accounts
        if balance < 300:
            adjusted_position_size = min(adjusted_position_size, 0.20)  # Max 20%
            adjusted_max_positions = min(adjusted_max_positions, 3)
            logger.debug(f"⚠️ Small account caps applied: max_pos={adjusted_max_positions}, max_size=20%")
        
        return {
            "position_size_percent": adjusted_position_size,
            "max_positions": adjusted_max_positions,
            "max_leverage": profile.max_leverage,
            "daily_risk_limit": profile.daily_risk_limit,
            "profile": profile.name,
            "performance_adjusted": profit_ratio != 1.0
        }
    
    def get_leverage_factor_by_balance(self, balance: float) -> float:
        """
        Get balance-based leverage multiplier (for dynamic leverage calculation).
        Similar to DynamicTradingAgent.get_balance_leverage_factor().
        
        Returns:
            Float 2.0-8.0 based on balance tier
        """
        if balance >= 5000:
            return 8.0
        elif balance >= 2000:
            return 6.0
        elif balance >= 1000:
            return 4.0
        elif balance >= 500:
            return 3.0
        else:
            return 2.0


# Singleton instance
_risk_profile_manager: Optional[RiskProfileManager] = None

def get_risk_profile_manager() -> RiskProfileManager:
    """Get singleton RiskProfileManager instance"""
    global _risk_profile_manager
    if _risk_profile_manager is None:
        _risk_profile_manager = RiskProfileManager()
    return _risk_profile_manager
