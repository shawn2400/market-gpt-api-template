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
        """
        🚨 AI-DRIVEN PARAMETERS - These are SUGGESTIONS, not hardcoded limits!
        
        AI has 100% freedom to calculate ALL parameters per-trade based on:
        - Entry quality (calculated by Deep Market Analyzer)
        - Volatility (ATR, Bollinger Bands)
        - Trend strength (ADX, momentum)
        - Market regime (TRENDING/CHOPPY/VOLATILE/SIDEWAYS)
        - Time in position
        - PnL trajectory
        - Portfolio state
        
        These values are MEDIAN suggestions from 5-brain consensus.
        AI can deviate freely within safe operational ranges.
        """
        return {
            "TRENDING": {
                "entry_quality_min": 4.0,  # AI suggestion - NOT enforced
                "sl_atr_multiplier": 1.5,  # AI suggestion - NOT enforced
                "tp_rr_ratio": 1.8,         # AI suggestion - NOT enforced
                "trail_atr_multiplier": 0.8, # AI suggestion - NOT enforced
                "default_leverage": 5       # AI suggestion - NOT enforced
            },
            "CHOPPY": {
                "entry_quality_min": 4.0,
                "sl_atr_multiplier": 1.5,
                "tp_rr_ratio": 1.8,
                "trail_atr_multiplier": 0.7,
                "default_leverage": 4
            },
            "VOLATILE": {
                "entry_quality_min": 4.0,
                "sl_atr_multiplier": 1.8,
                "tp_rr_ratio": 2.0,
                "trail_atr_multiplier": 0.9,
                "default_leverage": 4
            },
            "SIDEWAYS": {
                "entry_quality_min": 4.0,
                "sl_atr_multiplier": 1.5,
                "tp_rr_ratio": 1.6,
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
        🚨 WIDE SAFETY RANGES - AI has near-total freedom!
        
        These are ONLY for extreme safety - prevent clearly dangerous trades.
        AI can choose ANY value within these wide ranges per-trade.
        
        Philosophy: Trust AI to make smart decisions. Don't constrain creativity.
        
        ⚠️ DOWNSTREAM VALIDATION EXISTS:
        - Leverage: order_sanity.py, leverage_policy.py, precision_calculator.py enforce caps (10-35x depending on conditions)
        - Quality: risk_guard.py validates entry quality
        - Risk: risk_rules.py enforces LEV_HARD_CAP and other safety limits
        
        So AI can propose up to 15x leverage here, but downstream systems will cap it appropriately.
        This multi-layer validation = defense in depth!
        """
        return {
            "entry_quality_min": (2.0, 10.0),      # Very wide - AI decides what's "good enough"
            "sl_atr_multiplier": (0.5, 4.0),       # Very wide - from tight to very wide
            "tp_rr_ratio": (1.0, 5.0),             # Very wide - from 1:1 to 5:1
            "trail_atr_multiplier": (0.3, 2.0),    # Very wide - trail flexibility
            "default_leverage": (1, 15)            # Wide range - downstream systems enforce final caps!
        }


protection_manager = DynamicProtectionManager()
