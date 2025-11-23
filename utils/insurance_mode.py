# -*- coding: utf-8 -*-
"""
ULTRA-PLUS: Insurance Mode - Auto-hedge and position reduction during high risk.
Dynamic auto-activation when market conditions deteriorate.
"""

import os
import logging
from typing import Dict, Any, Optional
from contextlib import suppress

logger = logging.getLogger(__name__)

# Dynamic config
ENABLE_INSURANCE_MODE = os.getenv("ENABLE_INSURANCE_MODE", "1") == "1"
INSURANCE_FUNDING_THRESHOLD = float(os.getenv("INSURANCE_FUNDING_THRESHOLD", "0.05"))  # 5%
INSURANCE_VOLATILITY_THRESHOLD = float(os.getenv("INSURANCE_VOLATILITY_THRESHOLD", "4.0"))
INSURANCE_LOSS_THRESHOLD = float(os.getenv("INSURANCE_LOSS_THRESHOLD", "-0.03"))  # -3%


class InsuranceMode:
    """
    Automatically activates protective measures when risk conditions detected.
    Includes hedge positioning and position size reduction.
    """
    
    def __init__(self):
        self.enabled = ENABLE_INSURANCE_MODE
        self.active = False
        self.active_since = None
        self.activation_count = 0
    
    def evaluate(self, position: Optional[Dict[str, Any]] = None,
                 funding_rate: float = 0.0, 
                 volatility: float = 0.0) -> Dict[str, Any]:
        """
        Evaluate if insurance measures should activate.
        Dynamic activation based on multiple risk factors.
        
        Args:
            position: Current position data (optional)
            funding_rate: Current funding rate (1% = 0.01)
            volatility: Current market volatility
        
        Returns:
            Insurance recommendation
        """
        if not self.enabled:
            return {"insurance_active": False, "actions": []}
        
        recommendation = {
            "insurance_active": False,
            "hedge": False,
            "reduce_position_by": 0.0,
            "reasons": []
        }
        
        # Check funding rate risk
        if funding_rate > INSURANCE_FUNDING_THRESHOLD:
            recommendation["insurance_active"] = True
            recommendation["hedge"] = True
            recommendation["reduce_position_by"] = max(recommendation.get("reduce_position_by", 0), 0.3)
            recommendation["reasons"].append(
                f"high_funding_rate={funding_rate:.4f} (threshold: {INSURANCE_FUNDING_THRESHOLD})"
            )
        
        # Check volatility risk
        if volatility > INSURANCE_VOLATILITY_THRESHOLD:
            recommendation["insurance_active"] = True
            recommendation["hedge"] = True
            recommendation["reduce_position_by"] = max(recommendation.get("reduce_position_by", 0), 0.2)
            recommendation["reasons"].append(
                f"high_volatility={volatility:.2f} (threshold: {INSURANCE_VOLATILITY_THRESHOLD})"
            )
        
        # Check unrealized loss risk
        if position:
            unrealized_pnl = position.get("unrealized_pnl", 0)
            if unrealized_pnl < INSURANCE_LOSS_THRESHOLD:
                recommendation["insurance_active"] = True
                recommendation["hedge"] = True
                recommendation["reduce_position_by"] = max(recommendation.get("reduce_position_by", 0), 0.5)
                recommendation["reasons"].append(
                    f"unrealized_loss={unrealized_pnl:.4f} (threshold: {INSURANCE_LOSS_THRESHOLD})"
                )
        
        if recommendation["insurance_active"]:
            self.active = True
            self.activation_count += 1
            logger.warning(
                f"⚠️  Insurance Mode ACTIVE - Reasons: {', '.join(recommendation['reasons'])}"
            )
        else:
            self.active = False
        
        return recommendation
    
    def get_position_reduction_multiplier(self, recommendation: Dict[str, Any]) -> float:
        """
        Convert position reduction percentage to size multiplier.
        
        Args:
            recommendation: Insurance recommendation
        
        Returns:
            Position size multiplier (1.0 = no reduction, 0.5 = 50% reduction)
        """
        reduce_by = recommendation.get("reduce_position_by", 0.0)
        return round(1.0 - reduce_by, 3)
    
    def should_hedge(self, recommendation: Dict[str, Any]) -> bool:
        """Check if hedge position should be opened."""
        return recommendation.get("hedge", False)
    
    def get_hedge_size_ratio(self, recommendation: Dict[str, Any]) -> float:
        """Get hedge position size as ratio of main position."""
        if not recommendation.get("hedge"):
            return 0.0
        
        reduce_by = recommendation.get("reduce_position_by", 0.0)
        return round(min(reduce_by * 2, 0.5), 3)  # Cap hedge at 50%
    
    def deactivate(self) -> bool:
        """Manually deactivate insurance mode."""
        if self.active:
            self.active = False
            logger.info("✅ Insurance Mode deactivated")
            return True
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get insurance mode status."""
        return {
            "enabled": self.enabled,
            "active": self.active,
            "activation_count": self.activation_count,
            "funding_threshold": INSURANCE_FUNDING_THRESHOLD,
            "volatility_threshold": INSURANCE_VOLATILITY_THRESHOLD,
            "loss_threshold": INSURANCE_LOSS_THRESHOLD
        }


# Global singleton
_insurance_mode = None


def get_insurance_mode() -> InsuranceMode:
    """Get or create global insurance mode (singleton)."""
    global _insurance_mode
    if _insurance_mode is None:
        _insurance_mode = InsuranceMode()
        if ENABLE_INSURANCE_MODE:
            logger.info("✅ Insurance Mode initialized (dynamic auto-activation enabled)")
        else:
            logger.info("ℹ️  Insurance Mode disabled")
    return _insurance_mode
