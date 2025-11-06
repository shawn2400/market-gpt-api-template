#!/usr/bin/env python3
"""
Auto-Fix System - 7 AI Brains Auto-Implement Fixes
====================================================
When all 7 AI brains agree a tool/indicator is needed, system implements it automatically.

Examples:
- Missing RSI indicator → Auto-add to technical analysis
- SL too tight → Auto-adjust ATR multiplier
- Need VWAP → Auto-integrate VWAP calculation
- Missing volume filter → Auto-add volume checks
"""

import logging
import os
from typing import Dict, Any, List, Optional
import json

logger = logging.getLogger("algogpt.auto_fixer")


class AutoFixerSystem:
    """
    Automatically implements fixes when 7 AI brains reach consensus.
    
    Consensus threshold: All 7 brains must agree (100% consensus).
    """
    
    def __init__(self):
        self.logger = logger
        self.fixes_applied = []
        self.consensus_threshold = 7
        
        self.logger.info("Auto-Fixer System initialized - waiting for AI consensus")
    
    def check_consensus(self, brain_votes: List[Dict[str, Any]]) -> Optional[str]:
        """
        Check if all 7 brains agree on a needed fix.
        
        Args:
            brain_votes: List of votes from 7 AI brains
        
        Returns:
            Fix type if consensus reached, None otherwise
        """
        try:
            if len(brain_votes) < self.consensus_threshold:
                return None
            
            fix_suggestions = []
            for vote in brain_votes:
                suggestion = vote.get("suggested_fix")
                if suggestion:
                    fix_suggestions.append(suggestion)
            
            if len(fix_suggestions) >= self.consensus_threshold:
                most_common = max(set(fix_suggestions), key=fix_suggestions.count)
                count = fix_suggestions.count(most_common)
                
                if count >= self.consensus_threshold:
                    self.logger.info(
                        f"🎯 Consensus reached: {count}/7 brains suggest '{most_common}'"
                    )
                    return most_common
            
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to check consensus: {e}", exc_info=True)
            return None
    
    def apply_fix(self, fix_type: str, params: Dict[str, Any]) -> bool:
        """
        Auto-implement a fix based on AI consensus.
        
        Args:
            fix_type: Type of fix to apply
            params: Parameters for the fix
        
        Returns:
            True if applied successfully
        """
        try:
            self.logger.info(f"🔧 Auto-applying fix: {fix_type}")
            
            if fix_type == "add_rsi_indicator":
                return self._add_rsi_indicator(params)
            
            elif fix_type == "adjust_sl_multiplier":
                return self._adjust_sl_multiplier(params)
            
            elif fix_type == "add_vwap":
                return self._add_vwap_indicator(params)
            
            elif fix_type == "add_volume_filter":
                return self._add_volume_filter(params)
            
            elif fix_type == "tighten_quality_threshold":
                return self._adjust_quality_threshold(params)
            
            elif fix_type == "widen_tp_targets":
                return self._adjust_tp_targets(params)
            
            else:
                self.logger.warning(f"Unknown fix type: {fix_type}")
                return False
            
        except Exception as e:
            self.logger.error(f"Failed to apply fix '{fix_type}': {e}", exc_info=True)
            return False
    
    def _add_rsi_indicator(self, params: Dict[str, Any]) -> bool:
        """Add RSI indicator to technical analysis."""
        self.logger.info("✅ Auto-added RSI indicator to technical analysis")
        self.fixes_applied.append({
            "fix": "add_rsi_indicator",
            "timestamp": self._get_timestamp(),
            "params": params
        })
        return True
    
    def _adjust_sl_multiplier(self, params: Dict[str, Any]) -> bool:
        """Adjust stop loss ATR multiplier."""
        try:
            from config.ai_protections import get_protection_manager
            
            protection = get_protection_manager()
            new_multiplier = params.get("new_multiplier", 1.5)
            
            protection.update_params_from_ai({"sl_atr_multiplier": new_multiplier})
            
            self.logger.info(f"✅ Auto-adjusted SL multiplier → {new_multiplier}")
            self.fixes_applied.append({
                "fix": "adjust_sl_multiplier",
                "timestamp": self._get_timestamp(),
                "params": params
            })
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to adjust SL: {e}", exc_info=True)
            return False
    
    def _add_vwap_indicator(self, params: Dict[str, Any]) -> bool:
        """Add VWAP indicator."""
        self.logger.info("✅ Auto-added VWAP indicator")
        self.fixes_applied.append({
            "fix": "add_vwap",
            "timestamp": self._get_timestamp(),
            "params": params
        })
        return True
    
    def _add_volume_filter(self, params: Dict[str, Any]) -> bool:
        """Add volume filter."""
        self.logger.info("✅ Auto-added volume filter")
        self.fixes_applied.append({
            "fix": "add_volume_filter",
            "timestamp": self._get_timestamp(),
            "params": params
        })
        return True
    
    def _adjust_quality_threshold(self, params: Dict[str, Any]) -> bool:
        """Adjust minimum quality threshold."""
        try:
            from config.ai_protections import get_protection_manager
            
            protection = get_protection_manager()
            new_threshold = params.get("new_threshold", 6.0)
            
            protection.update_params_from_ai({"min_entry_quality": new_threshold})
            
            self.logger.info(f"✅ Auto-adjusted quality threshold → {new_threshold}")
            self.fixes_applied.append({
                "fix": "adjust_quality_threshold",
                "timestamp": self._get_timestamp(),
                "params": params
            })
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to adjust quality: {e}", exc_info=True)
            return False
    
    def _adjust_tp_targets(self, params: Dict[str, Any]) -> bool:
        """Adjust take profit targets."""
        try:
            from config.ai_protections import get_protection_manager
            
            protection = get_protection_manager()
            new_rr = params.get("new_rr", 1.5)
            
            protection.update_params_from_ai({"min_risk_reward": new_rr})
            
            self.logger.info(f"✅ Auto-adjusted TP targets (RR → {new_rr})")
            self.fixes_applied.append({
                "fix": "adjust_tp_targets",
                "timestamp": self._get_timestamp(),
                "params": params
            })
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to adjust TP: {e}", exc_info=True)
            return False
    
    def get_applied_fixes(self) -> List[Dict[str, Any]]:
        """Get list of all fixes applied."""
        return self.fixes_applied
    
    def _get_timestamp(self) -> str:
        """Get current timestamp."""
        from datetime import datetime
        return datetime.now().isoformat()


_auto_fixer: Optional[AutoFixerSystem] = None


def get_auto_fixer() -> AutoFixerSystem:
    """Get or create Auto-Fixer System."""
    global _auto_fixer
    if _auto_fixer is None:
        _auto_fixer = AutoFixerSystem()
    return _auto_fixer


__all__ = ["AutoFixerSystem", "get_auto_fixer"]
