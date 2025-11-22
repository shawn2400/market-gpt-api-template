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
        
        # Calculate TP prices - 🔧 EXTENDED to 5 LEVELS for maximum profit capture
        if side == "LONG":
            tp1_price = entry_price + (risk_amount * rrr)          # 100% of RR
            tp2_price = entry_price + (risk_amount * rrr * 1.5)    # 150% of RR
            tp3_price = entry_price + (risk_amount * rrr * 2.5)    # 250% of RR
            tp4_price = entry_price + (risk_amount * rrr * 3.5)    # 350% of RR (NEW)
            tp5_price = entry_price + (risk_amount * rrr * 4.5)    # 450% of RR (NEW)
            trailing_activation = tp3_price  # Only trigger after TP3
        else:  # SHORT
            tp1_price = entry_price - (risk_amount * rrr)
            tp2_price = entry_price - (risk_amount * rrr * 1.5)
            tp3_price = entry_price - (risk_amount * rrr * 2.5)
            tp4_price = entry_price - (risk_amount * rrr * 3.5)    # NEW
            tp5_price = entry_price - (risk_amount * rrr * 4.5)    # NEW
            trailing_activation = tp3_price  # Only trigger after TP3
        
        # Calculate trailing stop percentage (3-5% based on volatility)
        trailing_percent = self._calculate_trailing_percent(volatility)
        
        # 🎯 DYNAMIC EXIT PERCENTAGES (5 LEVELS now!)
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
                    "description": f"TP1: {rrr:.1f}R ({(abs(tp1_price-entry_price)/entry_price*100):.1f}%)"
                },
                {
                    "level": 2,
                    "price": tp2_price,
                    "exit_percent": exit_percentages[1],  # DYNAMIC!
                    "description": f"TP2: {rrr*1.5:.1f}R ({(abs(tp2_price-entry_price)/entry_price*100):.1f}%)"
                },
                {
                    "level": 3,
                    "price": tp3_price,
                    "exit_percent": exit_percentages[2],  # DYNAMIC!
                    "description": f"TP3: {rrr*2.5:.1f}R ({(abs(tp3_price-entry_price)/entry_price*100):.1f}%)"
                },
                {
                    "level": 4,
                    "price": tp4_price,
                    "exit_percent": exit_percentages[3] if len(exit_percentages) > 3 else 0.10,  # NEW!
                    "description": f"TP4: {rrr*3.5:.1f}R ({(abs(tp4_price-entry_price)/entry_price*100):.1f}%)"
                },
                {
                    "level": 5,
                    "price": tp5_price,
                    "exit_percent": exit_percentages[4] if len(exit_percentages) > 4 else 0.10,  # NEW!
                    "description": f"TP5: {rrr*4.5:.1f}R ({(abs(tp5_price-entry_price)/entry_price*100):.1f}%)"
                }
            ],
            "trailing_stop": {
                "enabled": False,  # DISABLED - let TP grid handle it
                "activation_price": trailing_activation,
                "trailing_percent": trailing_percent,
                "description": f"Trailing disabled - use full TP grid to TP5"
            },
            "risk_reward_ratio": rrr,
            "total_exit_percent": 1.0,  # Distributed across 5 levels
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
        Calculate DYNAMIC exit percentages for 5 TP levels.
        
        Base profiles:
        - Balanced: [0.20, 0.25, 0.30, 0.15, 0.10] - balanced across all 5 targets
        - Front-loaded: [0.30, 0.25, 0.25, 0.12, 0.08] - take profits early
        - Back-loaded: [0.15, 0.20, 0.30, 0.20, 0.15] - hold for bigger targets
        
        Args:
            volatility: ATR percentage (0.0-1.0)
            regime: Market regime (bull/bear/choppy/volatile)
            strategy: Trading strategy type
            win_rate: Historical win rate (0.0-1.0), if available
            
        Returns:
            List of 3 exit percentages that sum to 1.0
        """
        # Start with balanced profile (5 levels)
        tp1_pct = 0.20  # First target: 20%
        tp2_pct = 0.25  # Second target: 25%
        tp3_pct = 0.30  # Third target: 30%
        tp4_pct = 0.15  # Fourth target: 15%
        tp5_pct = 0.10  # Fifth target: 10%
        
        # Adjust based on volatility
        if volatility > 0.10:  # High volatility (>10%)
            # Front-load: Take profits faster before reversal
            tp1_pct += 0.10  # 30%
            tp4_pct -= 0.05  # 10%
            tp5_pct -= 0.05  # 5%
        elif volatility < 0.03:  # Very low volatility (<3%)
            # Back-load: Hold longer for bigger moves
            tp1_pct -= 0.05  # 15%
            tp3_pct += 0.05  # 35%
            tp4_pct += 0.05  # 20%
        
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
        
        # Ensure percentages are within reasonable bounds (5 levels)
        tp1_pct = max(0.10, min(0.35, tp1_pct))  # 10-35%
        tp2_pct = max(0.15, min(0.35, tp2_pct))  # 15-35%
        tp3_pct = max(0.20, min(0.40, tp3_pct))  # 20-40%
        tp4_pct = max(0.08, min(0.25, tp4_pct))  # 8-25%
        tp5_pct = max(0.05, min(0.15, tp5_pct))  # 5-15%
        
        # Normalize to ensure exactly 1.0 across all 5 levels
        total = tp1_pct + tp2_pct + tp3_pct + tp4_pct + tp5_pct
        if abs(total - 1.0) > 0.001:
            # Normalize to ensure exactly 1.0
            tp1_pct /= total
            tp2_pct /= total
            tp3_pct /= total
            tp4_pct /= total
            tp5_pct /= total
        
        self.logger.debug(
            f"Dynamic TP splits (5 levels): TP1={tp1_pct*100:.0f}%, TP2={tp2_pct*100:.0f}%, TP3={tp3_pct*100:.0f}%, TP4={tp4_pct*100:.0f}%, TP5={tp5_pct*100:.0f}% "
            f"(vol={volatility*100:.1f}%, regime={regime}, strategy={strategy}, wr={win_rate*100 if win_rate else 'N/A'})"
        )
        
        return [tp1_pct, tp2_pct, tp3_pct, tp4_pct, tp5_pct]
    
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
    
    def extend_tp_levels(
        self,
        current_tp_config: Dict[str, Any],
        last_tp_hit: int,
        current_price: float,
        remaining_quantity: float,
        volatility: float
    ) -> Optional[Dict[str, Any]]:
        """
        🚀 DYNAMIC TP EXTENSION: Generate new TP levels after TP3/TP4 hit.
        
        When price continues beyond TP3/TP4, automatically create new targets
        to capture extended profits instead of leaving remaining position unprotected.
        
        Args:
            current_tp_config: Current TP configuration
            last_tp_hit: Last TP level hit (3 or 4)
            current_price: Current market price
            remaining_quantity: Remaining position quantity
            volatility: Current ATR percentage
            
        Returns:
            New TP configuration with TP4/TP5, or None if extension not needed
        """
        if last_tp_hit < 3 or remaining_quantity <= 0:
            return None
        
        # Get original parameters
        side = current_tp_config.get("side", "LONG")
        rrr = current_tp_config.get("risk_reward_ratio", 2.0)
        
        # Get last TP price
        targets = current_tp_config.get("targets", [])
        if not targets or last_tp_hit > len(targets):
            return None
        
        last_tp_price = targets[last_tp_hit - 1]["price"]
        
        # Calculate extension distance based on volatility
        # Higher volatility = wider spacing between extended TPs
        if volatility > 0.10:
            extension_multiplier = 1.5  # 150% extension for high volatility
        elif volatility > 0.05:
            extension_multiplier = 1.3  # 130% extension for medium volatility
        else:
            extension_multiplier = 1.2  # 120% extension for low volatility
        
        # Calculate distance from previous TP
        if len(targets) >= 2:
            # Use average distance between previous TPs
            distances = []
            for i in range(1, len(targets)):
                dist = abs(targets[i]["price"] - targets[i-1]["price"])
                distances.append(dist)
            avg_distance = sum(distances) / len(distances)
        else:
            # Fallback: use 2% of current price
            avg_distance = current_price * 0.02
        
        # Generate new TP levels
        new_targets = []
        
        # TP4 (if we hit TP3)
        if last_tp_hit == 3:
            if side == "LONG":
                tp4_price = last_tp_price + (avg_distance * extension_multiplier)
            else:  # SHORT
                tp4_price = last_tp_price - (avg_distance * extension_multiplier)
            
            new_targets.append({
                "level": 4,
                "price": tp4_price,
                "exit_percent": 0.50,  # Exit 50% of remaining
                "description": f"TP4: Extended Target (auto-generated, +{extension_multiplier*100:.0f}% spacing)"
            })
            
            # TP5 (runner)
            if side == "LONG":
                tp5_price = tp4_price + (avg_distance * extension_multiplier * 1.2)
            else:  # SHORT
                tp5_price = tp4_price - (avg_distance * extension_multiplier * 1.2)
            
            new_targets.append({
                "level": 5,
                "price": tp5_price,
                "exit_percent": 0.50,  # Exit remaining 50%
                "description": f"TP5: Runner Target (auto-generated, extended)"
            })
        
        # TP5/TP6 (if we hit TP4)
        elif last_tp_hit == 4:
            if side == "LONG":
                tp5_price = last_tp_price + (avg_distance * extension_multiplier * 1.3)
                tp6_price = tp5_price + (avg_distance * extension_multiplier * 1.5)
            else:  # SHORT
                tp5_price = last_tp_price - (avg_distance * extension_multiplier * 1.3)
                tp6_price = tp5_price - (avg_distance * extension_multiplier * 1.5)
            
            new_targets.append({
                "level": 5,
                "price": tp5_price,
                "exit_percent": 0.60,  # Exit 60% of remaining
                "description": f"TP5: Extended Runner (auto-generated)"
            })
            
            new_targets.append({
                "level": 6,
                "price": tp6_price,
                "exit_percent": 0.40,  # Exit final 40%
                "description": f"TP6: Final Target (auto-generated)"
            })
        
        if not new_targets:
            return None
        
        # Create extended TP configuration
        extended_config = {
            "targets": new_targets,
            "trailing_stop": {
                "enabled": True,
                "activation_price": new_targets[0]["price"],
                "trailing_percent": current_tp_config["trailing_stop"]["trailing_percent"],
                "description": f"Trailing activates at TP{new_targets[0]['level']}"
            },
            "risk_reward_ratio": rrr,
            "side": side,
            "is_extended": True,
            "original_tp_hit": last_tp_hit
        }
        
        self.logger.info(
            f"🚀 TP Extension: Generated TP{new_targets[0]['level']}-TP{new_targets[-1]['level']} "
            f"after TP{last_tp_hit} hit | Price: {current_price:.4f} | "
            f"Targets: {[t['price'] for t in new_targets]}"
        )
        
        return extended_config


# Singleton instance
_multi_target_tp: Optional[MultiTargetTP] = None

def get_multi_target_tp() -> MultiTargetTP:
    """Get singleton MultiTargetTP instance"""
    global _multi_target_tp
    if _multi_target_tp is None:
        _multi_target_tp = MultiTargetTP()
    return _multi_target_tp
