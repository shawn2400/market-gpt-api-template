"""
Auto Parameter Tuner - Self-Optimizing Trade Parameters
========================================================
Automatically adjusts min_quality, risk_reward, and leverage based on
real-world performance to continuously improve win rate.

Features:
- Analyzes last 7-30 days of performance
- Adjusts thresholds when win rate < 35% or > 55%
- Increases strictness when losing, relaxes when winning
- Updates dynamic_filters.py automatically

Author: AlgoGPT Team
"""

import logging
import os
from typing import Dict, Tuple
from datetime import datetime

from utils.performance_tracker import get_performance_tracker
from utils.dynamic_filters import DynamicFilters

LOGGER = logging.getLogger("auto_parameter_tuner")


class AutoParameterTuner:
    """
    Tunes trading parameters based on performance feedback.
    
    Strategy:
    - Win rate < 35% → Increase min_quality, increase RR, decrease leverage
    - Win rate > 55% → Decrease min_quality, decrease RR, increase leverage
    - Win rate 35-55% → Keep current parameters (working zone)
    """
    
    def __init__(self):
        self.logger = LOGGER
        self.performance_tracker = get_performance_tracker()
        self.dynamic_filters = DynamicFilters()
        
        # Safety bounds (prevent extreme values)
        self.MIN_QUALITY_BOUNDS = (3.0, 8.0)
        self.RR_BOUNDS = (1.2, 3.0)
        self.LEVERAGE_BOUNDS = (5, 20)
    
    def analyze_and_tune(self, days: int = 7) -> Dict:
        """
        Analyze recent performance and adjust parameters accordingly.
        
        Args:
            days: Lookback period for analysis
            
        Returns:
            Dict with recommendations and changes made
        """
        self.logger.info(f"🔧 Starting auto-tuning analysis (last {days} days)")
        
        # Get current performance metrics
        overall_stats = self.performance_tracker.get_win_rate(days=days)
        win_rate = overall_stats.get("win_rate", 0.0)
        total_trades = overall_stats.get("total_trades", 0)
        
        if total_trades < 5:
            self.logger.info(f"⏸️ Insufficient data for tuning (only {total_trades} trades)")
            return {
                "action": "skip",
                "reason": "insufficient_data",
                "trades": total_trades,
                "min_required": 5
            }
        
        self.logger.info(f"📊 Current Performance: Win Rate {win_rate:.1f}% ({total_trades} trades)")
        
        # Get current parameters
        current_params = self._get_current_parameters()
        
        # Determine tuning direction
        tuning_result = self._calculate_parameter_adjustments(
            win_rate=win_rate,
            total_trades=total_trades,
            current_params=current_params
        )
        
        # Apply changes if needed
        if tuning_result["action"] == "adjust":
            self._apply_parameter_changes(tuning_result["new_params"])
            
            self.logger.info(
                f"✅ Parameters adjusted: "
                f"min_quality: {current_params['min_quality']:.1f} → {tuning_result['new_params']['min_quality']:.1f}, "
                f"RR: {current_params['min_rr']:.2f} → {tuning_result['new_params']['min_rr']:.2f}, "
                f"leverage: {current_params['max_leverage']} → {tuning_result['new_params']['max_leverage']}"
            )
        else:
            self.logger.info(f"✅ Parameters stable (win rate in optimal range)")
        
        return tuning_result
    
    def _get_current_parameters(self) -> Dict:
        """Get current parameter values from dynamic filters"""
        return {
            "min_quality": self.dynamic_filters.min_quality_score,
            "min_rr": self.dynamic_filters.min_rr_top10,
            "max_leverage": 15  # Default from config
        }
    
    def _calculate_parameter_adjustments(
        self,
        win_rate: float,
        total_trades: int,
        current_params: Dict
    ) -> Dict:
        """
        Calculate parameter adjustments based on win rate.
        
        Tuning Logic:
        - Win rate < 25%: EMERGENCY - strict parameters
        - Win rate < 35%: Conservative - increase quality requirements
        - Win rate 35-55%: Optimal zone - no changes
        - Win rate > 55%: Aggressive - relax requirements for more trades
        """
        if 35 <= win_rate <= 55:
            return {
                "action": "maintain",
                "reason": "optimal_performance",
                "win_rate": win_rate,
                "current_params": current_params
            }
        
        # Calculate adjustment factors
        if win_rate < 25:
            # EMERGENCY: Very strict
            adjustment = {
                "min_quality_delta": +2.0,
                "min_rr_delta": +0.5,
                "leverage_delta": -5,
                "reason": "emergency_mode"
            }
        elif win_rate < 35:
            # Conservative: Increase strictness
            adjustment = {
                "min_quality_delta": +1.0,
                "min_rr_delta": +0.3,
                "leverage_delta": -2,
                "reason": "below_target"
            }
        elif win_rate > 60:
            # Very aggressive: Relax significantly
            adjustment = {
                "min_quality_delta": -1.5,
                "min_rr_delta": -0.3,
                "leverage_delta": +3,
                "reason": "excellent_performance"
            }
        else:
            # Moderately aggressive: Relax slightly
            adjustment = {
                "min_quality_delta": -0.5,
                "min_rr_delta": -0.2,
                "leverage_delta": +1,
                "reason": "above_target"
            }
        
        # Calculate new parameters with safety bounds
        new_params = {
            "min_quality": self._clamp(
                current_params["min_quality"] + adjustment["min_quality_delta"],
                *self.MIN_QUALITY_BOUNDS
            ),
            "min_rr": self._clamp(
                current_params["min_rr"] + adjustment["min_rr_delta"],
                *self.RR_BOUNDS
            ),
            "max_leverage": int(self._clamp(
                current_params["max_leverage"] + adjustment["leverage_delta"],
                *self.LEVERAGE_BOUNDS
            ))
        }
        
        return {
            "action": "adjust",
            "reason": adjustment["reason"],
            "win_rate": win_rate,
            "total_trades": total_trades,
            "current_params": current_params,
            "new_params": new_params,
            "deltas": {
                "min_quality": adjustment["min_quality_delta"],
                "min_rr": adjustment["min_rr_delta"],
                "leverage": adjustment["leverage_delta"]
            }
        }
    
    def _apply_parameter_changes(self, new_params: Dict):
        """Apply new parameters to dynamic filters"""
        self.dynamic_filters.min_quality_score = new_params["min_quality"]
        self.dynamic_filters.min_rr_top10 = new_params["min_rr"]
        self.dynamic_filters.min_rr_alt = new_params["min_rr"] + 0.1
        
        # Save updated configuration
        self.dynamic_filters.save_config()
        
        self.logger.info(f"✅ New parameters applied and saved")
    
    def _clamp(self, value: float, min_val: float, max_val: float) -> float:
        """Clamp value between min and max bounds"""
        return max(min_val, min(max_val, value))


def run_auto_tuning(days: int = 7) -> Dict:
    """
    Convenience function to run auto-tuning analysis.
    
    Args:
        days: Lookback period
        
    Returns:
        Tuning result dictionary
    """
    tuner = AutoParameterTuner()
    return tuner.analyze_and_tune(days=days)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_auto_tuning(days=7)
    print(f"Tuning Result: {result}")
