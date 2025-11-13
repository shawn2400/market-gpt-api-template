# utils/tiered_grid_system.py
import os
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("algogpt.grid_tiers")


@dataclass
class GridTierConfig:
    tier_name: str
    min_orders: int
    max_orders: int
    grid_spacing_pct: float
    max_leverage: int
    max_investment_usdt: float
    profit_target_pct: float
    stop_loss_pct: float
    description: str


class TieredGridSystem:
    def __init__(self):
        self.tiers = {
            'Platinum': GridTierConfig(
                tier_name='Platinum',
                min_orders=8,
                max_orders=12,
                grid_spacing_pct=0.008,
                max_leverage=15,
                max_investment_usdt=500.0,
                profit_target_pct=0.05,
                stop_loss_pct=-0.03,
                description='Ultra-stable giants - tight spacing, high order count'
            ),
            'Gold': GridTierConfig(
                tier_name='Gold',
                min_orders=6,
                max_orders=10,
                grid_spacing_pct=0.010,
                max_leverage=12,
                max_investment_usdt=400.0,
                profit_target_pct=0.06,
                stop_loss_pct=-0.035,
                description='High-quality performers - balanced parameters'
            ),
            'Silver': GridTierConfig(
                tier_name='Silver',
                min_orders=5,
                max_orders=8,
                grid_spacing_pct=0.012,
                max_leverage=10,
                max_investment_usdt=300.0,
                profit_target_pct=0.07,
                stop_loss_pct=-0.04,
                description='Solid performers - moderate risk'
            ),
            'Bronze': GridTierConfig(
                tier_name='Bronze',
                min_orders=4,
                max_orders=6,
                grid_spacing_pct=0.015,
                max_leverage=8,
                max_investment_usdt=200.0,
                profit_target_pct=0.08,
                stop_loss_pct=-0.045,
                description='Cautious entry - wider spacing, lower exposure'
            )
        }
        
        logger.info(f"TieredGridSystem initialized with {len(self.tiers)} tiers")
    
    def get_tier_config(self, tier_name: str) -> Optional[GridTierConfig]:
        return self.tiers.get(tier_name)
    
    def get_grid_params(self, symbol: str, tier: Optional[str] = None) -> Dict[str, Any]:
        if not tier:
            logger.warning(f"No tier provided for {symbol}, using Bronze (default)")
            tier = 'Bronze'
        
        config = self.get_tier_config(tier)
        if not config:
            logger.error(f"Unknown tier '{tier}', using Bronze fallback")
            config = self.tiers['Bronze']
        
        params = {
            'symbol': symbol,
            'tier': config.tier_name,
            'min_orders': config.min_orders,
            'max_orders': config.max_orders,
            'grid_spacing_pct': config.grid_spacing_pct,
            'max_leverage': config.max_leverage,
            'max_investment_usdt': config.max_investment_usdt,
            'profit_target_pct': config.profit_target_pct,
            'stop_loss_pct': config.stop_loss_pct,
            'description': config.description
        }
        
        return params
    
    def calculate_grid_orders(
        self,
        symbol: str,
        tier: str,
        current_price: float,
        direction: str = 'LONG'
    ) -> Dict[str, Any]:
        config = self.get_tier_config(tier)
        if not config:
            logger.error(f"Unknown tier {tier}")
            return {}
        
        import random
        order_count = random.randint(config.min_orders, config.max_orders)
        
        spacing = config.grid_spacing_pct
        
        orders = []
        if direction == 'LONG':
            for i in range(order_count):
                buy_price = current_price * (1 - spacing * i)
                sell_price = buy_price * (1 + spacing)
                orders.append({
                    'level': i + 1,
                    'buy_price': round(buy_price, 8),
                    'sell_price': round(sell_price, 8),
                    'quantity_usdt': config.max_investment_usdt / order_count
                })
        else:
            for i in range(order_count):
                sell_price = current_price * (1 + spacing * i)
                buy_price = sell_price * (1 - spacing)
                orders.append({
                    'level': i + 1,
                    'sell_price': round(sell_price, 8),
                    'buy_price': round(buy_price, 8),
                    'quantity_usdt': config.max_investment_usdt / order_count
                })
        
        return {
            'symbol': symbol,
            'tier': tier,
            'direction': direction,
            'order_count': order_count,
            'spacing_pct': spacing * 100,
            'max_leverage': config.max_leverage,
            'total_investment': config.max_investment_usdt,
            'orders': orders
        }
    
    def get_tier_summary(self) -> Dict[str, Dict[str, Any]]:
        summary = {}
        for tier_name, config in self.tiers.items():
            summary[tier_name] = {
                'orders': f"{config.min_orders}-{config.max_orders}",
                'spacing': f"{config.grid_spacing_pct * 100:.1f}%",
                'max_leverage': config.max_leverage,
                'max_investment': config.max_investment_usdt,
                'profit_target': f"{config.profit_target_pct * 100:.1f}%",
                'stop_loss': f"{config.stop_loss_pct * 100:.1f}%",
                'description': config.description
            }
        return summary


_tier_system_instance: Optional[TieredGridSystem] = None

def get_tier_system() -> TieredGridSystem:
    global _tier_system_instance
    if _tier_system_instance is None:
        _tier_system_instance = TieredGridSystem()
    return _tier_system_instance
