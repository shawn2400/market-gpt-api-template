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
import json

from utils.performance_tracker import get_performance_tracker
from utils.dynamic_filters import save_filter_overrides, _load_overrides, BASE_QUALITY, BASE_RR_TOP10, BASE_RR_ALT

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
        
        # Safety bounds (prevent extreme values)
        self.MIN_QUALITY_BOUNDS = (3.0, 8.0)
        self.RR_BOUNDS = (1.01, 3.0)
        self.LEVERAGE_BOUNDS = (5, 20)
        
        # Current parameters file
        self.params_file = "/tmp/auto_tuner_params.json"
        self._load_params()
    
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
        """Get current parameter values from overrides or defaults"""
        # Load from overrides first (live values from last tuning)
        overrides = _load_overrides()
        
        if overrides:
            return {
                "min_quality": overrides.get("min_quality", BASE_QUALITY),
                "min_rr": overrides.get("min_rr_top10", BASE_RR_TOP10),
                "max_leverage": overrides.get("max_leverage", 15)
            }
        
        # Fallback to defaults
        return {
            "min_quality": BASE_QUALITY,
            "min_rr": BASE_RR_TOP10,
            "max_leverage": 15
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
        """Apply and save new parameters via dynamic_filters override mechanism"""
        self.current_params = new_params
        self._save_params()
        
        # Save to dynamic_filters override file (this is what gpt_auto_suggest reads!)
        # Include both RR splits and leverage
        overrides = {
            "min_quality": new_params["min_quality"],
            "min_rr_top10": new_params["min_rr"],
            "min_rr_alt": new_params["min_rr"] + 0.1,  # Alt coins slightly higher RR
            "max_leverage": new_params["max_leverage"]
        }
        
        save_filter_overrides(overrides)
        
        self.logger.info(
            f"✅ New parameters applied: quality={new_params['min_quality']:.1f}, "
            f"rr={new_params['min_rr']:.2f}, leverage={new_params['max_leverage']}x"
        )
    
    def _load_params(self):
        """Load parameters from file"""
        try:
            if os.path.exists(self.params_file):
                with open(self.params_file, 'r') as f:
                    self.current_params = json.load(f)
            else:
                self.current_params = self._get_current_parameters()
        except Exception as e:
            self.logger.warning(f"Failed to load params: {e}")
            self.current_params = self._get_current_parameters()
    
    def _save_params(self):
        """Save parameters to file (local tracking)"""
        try:
            with open(self.params_file, 'w') as f:
                json.dump(self.current_params, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to save params: {e}")
    
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
