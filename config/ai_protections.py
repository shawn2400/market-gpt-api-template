#!/usr/bin/env python3
"""
AI-Driven Protection Parameters
=================================
7 AI brains dynamically set protection parameters based on market conditions.

Base protections (starting point only):
- Entry Quality: ≥6.0 (flexible 5.5-7.0)
- Stop Loss: ATR × 1.5
- Take Profit: RR 1.5:1
- Break Even: +0.5%
- Trailing Stop: ATR × 0.8
- Leverage: 5x (flexible 2x-20x)

These are DYNAMIC - 7 AI brains adjust in real-time!
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("algogpt.ai_protections")


@dataclass
class ProtectionParams:
    """Dynamic protection parameters set by AI brains."""
    
    min_entry_quality: float = 6.0
    
    sl_atr_multiplier: float = 1.5
    
    min_risk_reward: float = 1.5
    
    breakeven_trigger_pct: float = 0.5
    
    trailing_atr_multiplier: float = 0.8
    
    base_leverage: int = 5
    
    leverage_min: int = 2
    leverage_max: int = 20
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            "min_entry_quality": self.min_entry_quality,
            "sl_atr_multiplier": self.sl_atr_multiplier,
            "min_risk_reward": self.min_risk_reward,
            "breakeven_trigger_pct": self.breakeven_trigger_pct,
            "trailing_atr_multiplier": self.trailing_atr_multiplier,
            "base_leverage": self.base_leverage,
            "leverage_range": f"{self.leverage_min}-{self.leverage_max}x"
        }


class AIProtectionManager:
    """
    Manages AI-driven protection parameters.
    
    7 AI brains can dynamically adjust these based on:
    - Market regime (TRENDING/CHOPPY/VOLATILE/SIDEWAYS)
    - Trade quality scores
    - Historical win rate
    - Current drawdown
    - Volatility levels
    """
    
    def __init__(self):
        self.logger = logger
        self.base_params = ProtectionParams()
        self.current_params = ProtectionParams()
        self.logger.info("AI Protection Manager initialized with base params")
    
    def calculate_stop_loss(
        self,
        entry_price: float,
        atr: float,
        direction: str,
        quality_score: float = 6.0,
        regime: str = "NEUTRAL"
    ) -> float:
        """
        Calculate dynamic stop loss based on ATR and AI decisions.
        
        Args:
            entry_price: Entry price
            atr: Average True Range
            direction: LONG or SHORT
            quality_score: Trade quality (5.5-10.0)
            regime: Market regime
        
        Returns:
            Stop loss price
        """
        try:
            multiplier = self.current_params.sl_atr_multiplier
            
            if quality_score >= 8.0:
                multiplier *= 0.9
            elif quality_score < 6.5:
                multiplier *= 1.1
            
            if regime == "VOLATILE":
                multiplier *= 1.2
            elif regime == "TRENDING":
                multiplier *= 0.95
            
            sl_distance = atr * multiplier
            
            if direction == "LONG":
                sl_price = entry_price - sl_distance
            else:
                sl_price = entry_price + sl_distance
            
            self.logger.debug(
                f"SL calculated: {sl_price:.2f} (ATR={atr:.2f}, "
                f"mult={multiplier:.2f}, quality={quality_score:.1f})"
            )
            
            return round(sl_price, 2)
            
        except Exception as e:
            self.logger.error(f"Failed to calculate SL: {e}", exc_info=True)
            
            fallback_pct = 0.02
            if direction == "LONG":
                return round(entry_price * (1 - fallback_pct), 2)
            else:
                return round(entry_price * (1 + fallback_pct), 2)
    
    def calculate_take_profit(
        self,
        entry_price: float,
        sl_price: float,
        direction: str,
        quality_score: float = 6.0,
        regime: str = "NEUTRAL"
    ) -> float:
        """
        Calculate dynamic take profit based on RR and AI decisions.
        
        Args:
            entry_price: Entry price
            sl_price: Stop loss price
            direction: LONG or SHORT
            quality_score: Trade quality
            regime: Market regime
        
        Returns:
            Take profit price
        """
        try:
            risk = abs(entry_price - sl_price)
            
            base_rr = self.current_params.min_risk_reward
            
            if quality_score >= 8.0:
                base_rr *= 1.3
            elif quality_score >= 7.0:
                base_rr *= 1.15
            
            if regime == "TRENDING":
                base_rr *= 1.2
            elif regime == "CHOPPY":
                base_rr *= 0.9
            
            reward = risk * base_rr
            
            if direction == "LONG":
                tp_price = entry_price + reward
            else:
                tp_price = entry_price - reward
            
            self.logger.debug(
                f"TP calculated: {tp_price:.2f} (RR={base_rr:.2f}, "
                f"risk=${risk:.2f}, reward=${reward:.2f})"
            )
            
            return round(tp_price, 2)
            
        except Exception as e:
            self.logger.error(f"Failed to calculate TP: {e}", exc_info=True)
            
            fallback_rr = 1.5
            reward = abs(entry_price - sl_price) * fallback_rr
            if direction == "LONG":
                return round(entry_price + reward, 2)
            else:
                return round(entry_price - reward, 2)
    
    def calculate_breakeven_trigger(
        self,
        entry_price: float,
        direction: str,
        quality_score: float = 6.0
    ) -> float:
        """
        Calculate when to move SL to breakeven.
        
        Args:
            entry_price: Entry price
            direction: LONG or SHORT
            quality_score: Trade quality
        
        Returns:
            Price level to trigger BE move
        """
        try:
            be_pct = self.current_params.breakeven_trigger_pct / 100
            
            if quality_score >= 8.0:
                be_pct *= 0.8
            elif quality_score < 6.5:
                be_pct *= 1.2
            
            if direction == "LONG":
                be_price = entry_price * (1 + be_pct)
            else:
                be_price = entry_price * (1 - be_pct)
            
            return round(be_price, 2)
            
        except Exception as e:
            self.logger.error(f"Failed to calculate BE: {e}", exc_info=True)
            return entry_price
    
    def calculate_trailing_distance(
        self,
        current_price: float,
        atr: float,
        direction: str,
        regime: str = "NEUTRAL"
    ) -> float:
        """
        Calculate trailing stop distance.
        
        Args:
            current_price: Current market price
            atr: Average True Range
            direction: LONG or SHORT
            regime: Market regime
        
        Returns:
            Trailing stop distance
        """
        try:
            multiplier = self.current_params.trailing_atr_multiplier
            
            if regime == "VOLATILE":
                multiplier *= 1.3
            elif regime == "TRENDING":
                multiplier *= 1.1
            
            distance = atr * multiplier
            
            self.logger.debug(
                f"Trailing distance: {distance:.2f} "
                f"(ATR={atr:.2f}, mult={multiplier:.2f})"
            )
            
            return round(distance, 2)
            
        except Exception as e:
            self.logger.error(f"Failed to calculate trailing: {e}", exc_info=True)
            return current_price * 0.01
    
    def update_params_from_ai(self, ai_recommendations: Dict[str, Any]) -> bool:
        """
        Update protection parameters based on AI brain recommendations.
        
        This is called after daily 00:00 review meetings when all 7 AI brains
        analyze performance and suggest improvements.
        
        Args:
            ai_recommendations: Dict with new parameter values
        
        Returns:
            True if updated successfully
        """
        try:
            if "min_entry_quality" in ai_recommendations:
                new_val = float(ai_recommendations["min_entry_quality"])
                if 5.0 <= new_val <= 8.0:
                    self.current_params.min_entry_quality = new_val
                    self.logger.info(f"Updated min_entry_quality → {new_val}")
            
            if "sl_atr_multiplier" in ai_recommendations:
                new_val = float(ai_recommendations["sl_atr_multiplier"])
                if 1.0 <= new_val <= 3.0:
                    self.current_params.sl_atr_multiplier = new_val
                    self.logger.info(f"Updated sl_atr_multiplier → {new_val}")
            
            if "min_risk_reward" in ai_recommendations:
                new_val = float(ai_recommendations["min_risk_reward"])
                if 1.2 <= new_val <= 3.0:
                    self.current_params.min_risk_reward = new_val
                    self.logger.info(f"Updated min_risk_reward → {new_val}")
            
            if "breakeven_trigger_pct" in ai_recommendations:
                new_val = float(ai_recommendations["breakeven_trigger_pct"])
                if 0.3 <= new_val <= 1.5:
                    self.current_params.breakeven_trigger_pct = new_val
                    self.logger.info(f"Updated breakeven_trigger_pct → {new_val}%")
            
            if "trailing_atr_multiplier" in ai_recommendations:
                new_val = float(ai_recommendations["trailing_atr_multiplier"])
                if 0.5 <= new_val <= 1.5:
                    self.current_params.trailing_atr_multiplier = new_val
                    self.logger.info(f"Updated trailing_atr_multiplier → {new_val}")
            
            self.logger.info("AI protection parameters updated successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to update AI params: {e}", exc_info=True)
            return False
    
    def get_current_params(self) -> Dict[str, Any]:
        """Get current protection parameters."""
        return self.current_params.to_dict()
    
    def update_settings(self, settings: Dict[str, Any]) -> bool:
        """
        Update protection settings (used by Multi-Level Protector).
        
        Args:
            settings: Dict with max_leverage, min_risk_reward, max_daily_trades, etc.
            
        Returns:
            True if updated successfully
        """
        try:
            if "max_leverage" in settings:
                new_val = int(settings["max_leverage"])
                if self.current_params.leverage_min <= new_val <= self.current_params.leverage_max:
                    self.current_params.base_leverage = new_val
                    self.logger.info(f"Updated max_leverage → {new_val}")
            
            if "min_risk_reward" in settings:
                new_val = float(settings["min_risk_reward"])
                if 1.2 <= new_val <= 3.0:
                    self.current_params.min_risk_reward = new_val
                    self.logger.info(f"Updated min_risk_reward → {new_val}")
            
            if "min_quality" in settings:
                new_val = float(settings["min_quality"])
                if 4.0 <= new_val <= 10.0:
                    self.current_params.min_entry_quality = new_val
                    self.logger.info(f"Updated min_entry_quality → {new_val}")
            
            self.logger.info("Protection settings updated via Multi-Level Protector")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to update settings: {e}", exc_info=True)
            return False
    
    def reset_to_base(self) -> None:
        """Reset to base parameters."""
        self.current_params = ProtectionParams()
        self.logger.warning("Protection parameters reset to base values")


_protection_manager: Optional[AIProtectionManager] = None


def get_protection_manager() -> AIProtectionManager:
    """Get or create AI Protection Manager."""
    global _protection_manager
    if _protection_manager is None:
        _protection_manager = AIProtectionManager()
    return _protection_manager


__all__ = ["AIProtectionManager", "ProtectionParams", "get_protection_manager"]
