"""
Dynamic Protection Manager - MetaBrain v9.0
Manages base protection parameters for 4 market regimes with AI consensus
"""
import json
import os
import logging
from typing import Dict, Literal

log = logging.getLogger(__name__)

MarketRegime = Literal["TRENDING", "CHOPPY", "VOLATILE", "SIDEWAYS"]

class DynamicProtectionManager:
    """
    Manages dynamic base protection parameters for each market regime.
    Parameters are updated via AI consensus from 5 brains.
    """
    
    def __init__(self, consensus_file: str = "/tmp/ai_brains_consensus.json"):
        self.consensus_file = consensus_file
        self.base_protections = self._load_base_protections()
        log.info(f"✅ Dynamic Protection Manager initialized with {len(self.base_protections)} regimes")
    
    def _load_base_protections(self) -> Dict[str, Dict[str, float]]:
        """Load base protection parameters from AI consensus file"""
        if os.path.exists(self.consensus_file):
            try:
                with open(self.consensus_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                log.warning(f"Could not load consensus file: {e}, using defaults")
        
        return self._get_default_protections()
    
    def _get_default_protections(self) -> Dict[str, Dict[str, float]]:
        """Default protection parameters (from AI consensus)"""
        return {
            "TRENDING": {
                "entry_quality_min": 5.8,
                "sl_atr_multiplier": 1.7,
                "tp_rr_ratio": 2.0,
                "be_trigger_pct": 0.4,
                "trail_atr_multiplier": 0.9,
                "default_leverage": 6
            },
            "CHOPPY": {
                "entry_quality_min": 6.5,
                "sl_atr_multiplier": 1.3,
                "tp_rr_ratio": 1.4,
                "be_trigger_pct": 0.6,
                "trail_atr_multiplier": 0.6,
                "default_leverage": 3
            },
            "VOLATILE": {
                "entry_quality_min": 6.2,
                "sl_atr_multiplier": 1.9,
                "tp_rr_ratio": 2.2,
                "be_trigger_pct": 0.5,
                "trail_atr_multiplier": 1.0,
                "default_leverage": 4
            },
            "SIDEWAYS": {
                "entry_quality_min": 6.0,
                "sl_atr_multiplier": 1.4,
                "tp_rr_ratio": 1.3,
                "be_trigger_pct": 0.6,
                "trail_atr_multiplier": 0.7,
                "default_leverage": 5
            }
        }
    
    def get_base_protection(self, regime: MarketRegime) -> Dict[str, float]:
        """Get base protection parameters for a specific regime"""
        return self.base_protections.get(regime, self.base_protections["CHOPPY"])
    
    def get_all_regimes(self) -> Dict[str, Dict[str, float]]:
        """Get all base protection parameters"""
        return self.base_protections
    
    def update_base_protection(self, regime: MarketRegime, params: Dict[str, float]):
        """Update base protection parameters for a regime (from AI consensus)"""
        self.base_protections[regime] = params
        self._save_to_file()
        log.info(f"✅ Updated base protection for {regime}: {params}")
    
    def _save_to_file(self):
        """Save current base protections to file"""
        try:
            with open(self.consensus_file, "w") as f:
                json.dump(self.base_protections, f, indent=2)
        except Exception as e:
            log.error(f"Failed to save base protections: {e}")
    
    def get_protection_ranges(self) -> Dict[str, tuple]:
        """
        Get allowed ranges for each parameter (for AI to stay within)
        These are the boundaries AI brains must respect
        """
        return {
            "entry_quality_min": (5.5, 7.0),
            "sl_atr_multiplier": (1.2, 2.0),
            "tp_rr_ratio": (1.2, 2.5),
            "be_trigger_pct": (0.3, 0.8),
            "trail_atr_multiplier": (0.5, 1.2),
            "default_leverage": (2, 8)
        }


protection_manager = DynamicProtectionManager()
