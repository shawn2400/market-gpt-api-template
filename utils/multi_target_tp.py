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
        side: str = "LONG",
        win_rate: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculate 3-level take profit targets with DYNAMIC exit percentages.
        
        Exit percentages adapt to:
        - Volatility: High volatility = aggressive early exits
        - Strategy: Grid balanced, breakout back-loaded, mean-reversion front-loaded
        - Regime: Bull = hold longer (back-loaded), Bear = take profits faster (front-loaded)
        - Win rate: High win rate = hold longer for bigger targets
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            strategy: Trading strategy
            volatility: ATR percentage (0.0-1.0)
            regime: Market regime (bull/bear/choppy/volatile)
            side: LONG or SHORT
            win_rate: Historical win rate (0.0-1.0), if available
            
        Returns:
            Dict with TP levels, DYNAMIC percentages, trailing stop config
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
        
        # 🎯 DYNAMIC EXIT PERCENTAGES (not hardcoded!)
        exit_percentages = self._calculate_dynamic_exit_percentages(
            volatility=volatility,
            regime=regime,
            strategy=strategy,
            win_rate=win_rate
        )
        
        return {
            "targets": [
                {
                    "level": 1,
                    "price": tp1_price,
                    "exit_percent": exit_percentages[0],  # DYNAMIC!
                    "description": f"TP1: {rrr*0.5:.1f}R ({(abs(tp1_price-entry_price)/entry_price*100):.1f}%)"
                },
                {
                    "level": 2,
                    "price": tp2_price,
                    "exit_percent": exit_percentages[1],  # DYNAMIC!
                    "description": f"TP2: {rrr:.1f}R ({(abs(tp2_price-entry_price)/entry_price*100):.1f}%)"
                },
                {
                    "level": 3,
                    "price": tp3_price,
                    "exit_percent": exit_percentages[2],  # DYNAMIC!
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
    
    def _calculate_dynamic_exit_percentages(
        self,
        volatility: float,
        regime: str,
        strategy: str,
        win_rate: Optional[float]
    ) -> List[float]:
        """
        Calculate DYNAMIC exit percentages for 3 TP levels.
        
        Base profiles:
        - Balanced: [0.30, 0.40, 0.30] - balanced exits
        - Front-loaded: [0.40, 0.35, 0.25] - take profits early (high volatility, bear market, mean-reversion)
        - Back-loaded: [0.25, 0.35, 0.40] - hold for bigger targets (low volatility, bull market, breakout)
        
        Args:
            volatility: ATR percentage (0.0-1.0)
            regime: Market regime (bull/bear/choppy/volatile)
            strategy: Trading strategy type
            win_rate: Historical win rate (0.0-1.0), if available
            
        Returns:
            List of 3 exit percentages that sum to 1.0
        """
        # Start with balanced profile
        tp1_pct = 0.30
        tp2_pct = 0.40
        tp3_pct = 0.30
        
        # Adjust based on volatility
        if volatility > 0.10:  # High volatility (>10%)
            # Front-load: Take profits faster before reversal
            tp1_pct += 0.10  # 40%
            tp3_pct -= 0.10  # 20%
        elif volatility < 0.03:  # Very low volatility (<3%)
            # Back-load: Hold longer for bigger moves
            tp1_pct -= 0.05  # 25%
            tp3_pct += 0.05  # 35%
        
        # Adjust based on regime
        regime_upper = regime.upper() if regime else "CHOPPY"
        if "BULL" in regime_upper or "TRENDING" in regime_upper:
            # Back-load: Ride the trend
            tp1_pct -= 0.05
            tp3_pct += 0.05
        elif "BEAR" in regime_upper or "VOLATILE" in regime_upper:
            # Front-load: Take profits before reversal
            tp1_pct += 0.05
            tp3_pct -= 0.05
        
        # Adjust based on strategy
        strategy_lower = strategy.lower() if strategy else ""
        if "mean_reversion" in strategy_lower or "grid" in strategy_lower:
            # Front-load: These strategies profit from quick reversals
            tp1_pct += 0.05
            tp3_pct -= 0.05
        elif "breakout" in strategy_lower or "trend" in strategy_lower:
            # Back-load: These strategies profit from continuation
            tp1_pct -= 0.05
            tp3_pct += 0.05
        
        # Adjust based on win rate (if available)
        if win_rate is not None:
            if win_rate > 0.65:  # High win rate (>65%)
                # Back-load: Trust the setup, hold for bigger targets
                tp1_pct -= 0.03
                tp3_pct += 0.03
            elif win_rate < 0.45:  # Low win rate (<45%)
                # Front-load: Take what you can get
                tp1_pct += 0.03
                tp3_pct -= 0.03
        
        # Ensure percentages are within reasonable bounds
        tp1_pct = max(0.20, min(0.50, tp1_pct))  # 20-50%
        tp3_pct = max(0.15, min(0.45, tp3_pct))  # 15-45%
        tp2_pct = 1.0 - tp1_pct - tp3_pct  # Middle level gets remainder
        
        # Ensure tp2 is at least 25%
        if tp2_pct < 0.25:
            deficit = 0.25 - tp2_pct
            tp2_pct = 0.25
            # Take from largest level
            if tp1_pct > tp3_pct:
                tp1_pct -= deficit
            else:
                tp3_pct -= deficit
        
        # Final validation: must sum to 1.0
        total = tp1_pct + tp2_pct + tp3_pct
        if abs(total - 1.0) > 0.001:
            # Normalize to ensure exactly 1.0
            tp1_pct /= total
            tp2_pct /= total
            tp3_pct /= total
        
        self.logger.debug(
            f"Dynamic TP splits: TP1={tp1_pct*100:.0f}%, TP2={tp2_pct*100:.0f}%, TP3={tp3_pct*100:.0f}% "
            f"(vol={volatility*100:.1f}%, regime={regime}, strategy={strategy}, wr={win_rate*100 if win_rate else 'N/A'})"
        )
        
        return [tp1_pct, tp2_pct, tp3_pct]
    
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
