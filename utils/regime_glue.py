# utils/regime_glue.py
"""
Regime-Based Parameter Adapter.
Dynamically adjusts trading parameters based on market regime.
Supports 4 regimes: TRENDING, CHOPPY, VOLATILE, SIDEWAYS
"""
from __future__ import annotations
import logging
import os
from typing import Dict, Any, Optional

log = logging.getLogger(__name__)


class RegimeAdapter:
    """
    Adapts trading parameters (SL/TP multipliers, trailing, management style)
    based on detected market regime.
    """

    def __init__(self):
        # Allow forcing a specific regime for testing
        self.force_regime = os.getenv("FORCE_REGIME", "").upper()

        # Regime profiles
        self.profiles = {
            "TRENDING": {
                "sl_atr_mult": 2.0,  # Wider SL for trends
                "tp_rr_mult": 2.5,  # Higher R:R
                "trail_enable": True,
                "trail_atr_mult": 1.5,
                "trail_freeze_enable": False,  # Don't freeze in trends
                "be_arm_pct": 1.8,  # Move to BE after 180% profit
                "strategy": "breakout",
            },
            "CHOPPY": {
                "sl_atr_mult": 1.2,  # Tighter SL
                "tp_rr_mult": 1.5,  # Lower R:R, take profits faster
                "trail_enable": False,  # No trailing in chop
                "trail_atr_mult": 0.0,
                "trail_freeze_enable": True,  # Freeze if spike
                "be_arm_pct": 1.2,  # Move to BE quickly
                "strategy": "mean_reversion",
            },
            "VOLATILE": {
                "sl_atr_mult": 2.5,  # Very wide SL
                "tp_rr_mult": 2.0,  # Moderate R:R
                "trail_enable": True,
                "trail_atr_mult": 2.0,  # Wide trailing
                "trail_freeze_enable": True,  # Freeze on spikes
                "be_arm_pct": 2.0,  # Higher threshold
                "strategy": "breakout",
            },
            "SIDEWAYS": {
                "sl_atr_mult": 1.5,  # Medium SL
                "tp_rr_mult": 1.8,  # Medium R:R
                "trail_enable": False,  # No trailing
                "trail_atr_mult": 0.0,
                "trail_freeze_enable": False,
                "be_arm_pct": 1.5,  # Moderate BE
                "strategy": "grid",
            },
        }

    def pick_params(
        self,
        regime: str,
        atr: float,
        entry_price: float,
        side: str = "LONG",
    ) -> Dict[str, Any]:
        """
        Select dynamic parameters based on regime.

        Args:
            regime: Market regime ("TRENDING", "CHOPPY", "VOLATILE", "SIDEWAYS")
            atr: ATR value for the symbol
            entry_price: Position entry price
            side: "LONG" or "SHORT"

        Returns:
            {
                "sl_price": float,
                "tp_price": float,
                "trail_enable": bool,
                "trail_atr_mult": float,
                "be_arm_pct": float,
                "strategy": str
            }
        """
        # Force regime if set
        if self.force_regime and self.force_regime in self.profiles:
            regime = self.force_regime
            log.info(f"[RegimeAdapter] Forced regime: {regime}")

        # Default to CHOPPY if unknown
        regime = regime.upper() if regime else "CHOPPY"
        if regime not in self.profiles:
            log.warning(f"[RegimeAdapter] Unknown regime '{regime}', defaulting to CHOPPY")
            regime = "CHOPPY"

        profile = self.profiles[regime]
        log.info(f"[RegimeAdapter] Using regime: {regime} (strategy: {profile['strategy']})")

        # Calculate SL price
        sl_atr_mult = profile["sl_atr_mult"]
        sl_distance = atr * sl_atr_mult
        if side == "LONG":
            sl_price = entry_price - sl_distance
        else:  # SHORT
            sl_price = entry_price + sl_distance

        # Calculate TP price (R:R based)
        tp_rr_mult = profile["tp_rr_mult"]
        tp_distance = sl_distance * tp_rr_mult
        if side == "LONG":
            tp_price = entry_price + tp_distance
        else:  # SHORT
            tp_price = entry_price - tp_distance

        return {
            "sl_price": max(0, sl_price),
            "tp_price": max(0, tp_price),
            "trail_enable": profile["trail_enable"],
            "trail_atr_mult": profile["trail_atr_mult"],
            "trail_freeze_enable": profile["trail_freeze_enable"],
            "be_arm_pct": profile["be_arm_pct"],
            "strategy": profile["strategy"],
            "regime": regime,
            "sl_atr_mult": sl_atr_mult,
            "tp_rr_mult": tp_rr_mult,
        }

    def get_tp_ladder_levels(
        self,
        regime: str,
        entry_price: float,
        atr: float,
        side: str = "LONG",
        num_levels: int = 3,
    ) -> list[float]:
        """
        Generate TP ladder prices based on regime.

        Args:
            regime: Market regime
            entry_price: Entry price
            atr: ATR value
            side: "LONG" or "SHORT"
            num_levels: Number of TP levels (2-4)

        Returns:
            List of TP prices [TP1, TP2, TP3, TP4]
        """
        if self.force_regime and self.force_regime in self.profiles:
            regime = self.force_regime

        regime = regime.upper() if regime else "CHOPPY"
        if regime not in self.profiles:
            regime = "CHOPPY"

        profile = self.profiles[regime]
        base_mult = profile["tp_rr_mult"]

        # Generate ladder: TP1 at base, TP2 at 1.5x, TP3 at 2x, TP4 at 3x
        multipliers = {
            2: [base_mult * 0.8, base_mult * 1.5],
            3: [base_mult * 0.8, base_mult * 1.5, base_mult * 2.0],
            4: [base_mult * 0.8, base_mult * 1.5, base_mult * 2.0, base_mult * 3.0],
        }

        mults = multipliers.get(min(num_levels, 4), multipliers[3])
        sl_distance = atr * profile["sl_atr_mult"]

        tp_prices = []
        for mult in mults:
            if side == "LONG":
                tp = entry_price + (sl_distance * mult)
            else:  # SHORT
                tp = entry_price - (sl_distance * mult)
            tp_prices.append(max(0, tp))

        log.info(f"[RegimeAdapter] {regime} TP ladder: {[f'{p:.4f}' for p in tp_prices]}")
        return tp_prices
