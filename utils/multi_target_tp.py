# -*- coding: utf-8 -*-
# utils/multi_target_tp.py
"""
Multi-Target Take Profit System
Implements 3-level TP with trailing stop (like AdvancedTradingSystem)
"""
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("algogpt.multi_target_tp")


class MultiTargetTP:
    """
    Multi-level take profit system with trailing stop.
    
    Features:
    - 3 TP targets with different exit percentages
    - Volatility-adjusted RR ratios
    - Regime-aware TP placement
    - Trailing stop activation at TP1
    """
    
    def __init__(self):
        self.logger = logger
    
    def calculate_tp_levels(
        self,
        entry_price: float,
        stop_loss: float,
        strategy: str,
        volatility: float,
        regime: str,
        side: str = "LONG"
    ) -> Dict[str, Any]:
        """
        Calculate 3-level take profit targets with trailing stop.
        
        Like AdvancedTradingSystem.calculate_optimal_take_profit():
        - TP1: 50% of RR (30% position exit)
        - TP2: 100% of RR (40% position exit)
        - TP3: 150% of RR (30% position exit)
        - Trailing stop activates at TP1
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            strategy: Trading strategy
            volatility: ATR percentage (0.0-1.0)
            regime: Market regime (bull/bear/choppy/volatile)
            side: LONG or SHORT
            
        Returns:
            Dict with TP levels, percentages, trailing stop config
        """
        # Calculate risk amount
        if side == "LONG":
            risk_amount = entry_price - stop_loss
        else:  # SHORT
            risk_amount = stop_loss - entry_price
        
        if risk_amount <= 0:
            self.logger.error(f"Invalid risk amount: entry={entry_price}, sl={stop_loss}, side={side}")
            # Fallback to 2% risk
            risk_amount = entry_price * 0.02
        
        # Base Risk/Reward ratio
        base_rrr = 2.0
        
        # Adjust RR based on volatility
        rrr = self._adjust_rrr_for_volatility(base_rrr, volatility)
        
        # Adjust RR based on regime
        rrr = self._adjust_rrr_for_regime(rrr, regime)
        
        # Calculate TP prices
        if side == "LONG":
            tp1_price = entry_price + (risk_amount * rrr * 0.5)  # 50% of RR
            tp2_price = entry_price + (risk_amount * rrr)        # 100% of RR
            tp3_price = entry_price + (risk_amount * rrr * 1.5)  # 150% of RR
            trailing_activation = tp1_price
        else:  # SHORT
            tp1_price = entry_price - (risk_amount * rrr * 0.5)
            tp2_price = entry_price - (risk_amount * rrr)
            tp3_price = entry_price - (risk_amount * rrr * 1.5)
            trailing_activation = tp1_price
        
        # Calculate trailing stop percentage (3-5% based on volatility)
        trailing_percent = self._calculate_trailing_percent(volatility)
        
        return {
            "targets": [
                {
                    "level": 1,
                    "price": tp1_price,
                    "exit_percent": 0.30,  # 30% of position
                    "description": f"TP1: {rrr*0.5:.1f}R ({(abs(tp1_price-entry_price)/entry_price*100):.1f}%)"
                },
                {
                    "level": 2,
                    "price": tp2_price,
                    "exit_percent": 0.40,  # 40% of position
                    "description": f"TP2: {rrr:.1f}R ({(abs(tp2_price-entry_price)/entry_price*100):.1f}%)"
                },
                {
                    "level": 3,
                    "price": tp3_price,
                    "exit_percent": 0.30,  # 30% of position
                    "description": f"TP3: {rrr*1.5:.1f}R ({(abs(tp3_price-entry_price)/entry_price*100):.1f}%)"
                }
            ],
            "trailing_stop": {
                "enabled": True,
                "activation_price": trailing_activation,
                "trailing_percent": trailing_percent,
                "description": f"Trailing activates at TP1 ({trailing_percent*100:.0f}% trail)"
            },
            "risk_reward_ratio": rrr,
            "total_exit_percent": 1.0,  # 30% + 40% + 30% = 100%
            "side": side
        }
    
    def _adjust_rrr_for_volatility(self, base_rrr: float, volatility: float) -> float:
        """
        Adjust RR ratio based on volatility.
        High volatility = higher RR targets (more room to run)
        """
        if volatility > 0.15:  # High volatility (>15%)
            return base_rrr * 1.3
        elif volatility < 0.05:  # Low volatility (<5%)
            return base_rrr * 0.8
        else:
            return base_rrr
    
    def _adjust_rrr_for_regime(self, rrr: float, regime: str) -> float:
        """
        Adjust RR ratio based on market regime.
        Bull market = higher targets, bear market = lower targets
        """
        regime_upper = regime.upper() if regime else "CHOPPY"
        
        if "BULL" in regime_upper or "TRENDING" in regime_upper:
            return rrr * 1.2  # 20% higher targets in bullish trends
        elif "BEAR" in regime_upper:
            return rrr * 0.8  # 20% lower targets in bearish trends
        else:
            return rrr  # Normal targets for choppy/sideways
    
    def _calculate_trailing_percent(self, volatility: float) -> float:
        """
        Calculate trailing stop percentage based on volatility.
        Higher volatility = wider trailing stop
        """
        if volatility > 0.15:
            return 0.05  # 5% trailing for high volatility
        elif volatility > 0.10:
            return 0.04  # 4% trailing for medium-high
        elif volatility > 0.05:
            return 0.03  # 3% trailing for medium
        else:
            return 0.02  # 2% trailing for low volatility
    
    def create_tp_orders(
        self,
        symbol: str,
        tp_config: Dict[str, Any],
        total_quantity: float,
        side: str = "LONG"
    ) -> List[Dict[str, Any]]:
        """
        Create individual TP orders for each target level.
        
        Args:
            symbol: Trading symbol
            tp_config: TP configuration from calculate_tp_levels()
            total_quantity: Total position quantity
            side: LONG or SHORT
            
        Returns:
            List of TP order specifications (LIMIT orders for reliability)
        """
        orders = []
        
        for target in tp_config["targets"]:
            # Calculate quantity for this level
            quantity = total_quantity * target["exit_percent"]
            
            # Determine order side (opposite of entry)
            order_side = "SELL" if side == "LONG" else "BUY"
            
            # Use LIMIT orders for TP (more reliable than TAKE_PROFIT_MARKET)
            # LIMIT works for both LONG and SHORT positions
            orders.append({
                "symbol": symbol,
                "side": order_side,
                "type": "LIMIT",
                "quantity": round(quantity, 4),
                "price": round(target["price"], 4),
                "reduceOnly": True,
                "timeInForce": "GTC",
                "level": target["level"],
                "description": target["description"]
            })
        
        return orders
    
    def format_tp_summary(self, tp_config: Dict[str, Any]) -> str:
        """Format TP configuration as human-readable string"""
        lines = [f"📊 Multi-Target TP (RR={tp_config['risk_reward_ratio']:.1f}):"]
        
        for target in tp_config["targets"]:
            lines.append(
                f"   {target['description']} → "
                f"Exit {target['exit_percent']*100:.0f}% @ {target['price']:.4f}"
            )
        
        trailing = tp_config["trailing_stop"]
        lines.append(
            f"   🔄 {trailing['description']} @ {trailing['activation_price']:.4f}"
        )
        
        return "\n".join(lines)


# Singleton instance
_multi_target_tp: Optional[MultiTargetTP] = None

def get_multi_target_tp() -> MultiTargetTP:
    """Get singleton MultiTargetTP instance"""
    global _multi_target_tp
    if _multi_target_tp is None:
        _multi_target_tp = MultiTargetTP()
    return _multi_target_tp
