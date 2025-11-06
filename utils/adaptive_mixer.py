# -*- coding: utf-8 -*-
"""
Adaptive Parameter Mixer
Dynamically adjusts SL/TP multipliers, trailing, and TP ladder levels
based on regime, confidence, volatility, PnL state, and position age.
"""
from __future__ import annotations
from typing import Dict, List, Any
import logging

log = logging.getLogger(__name__)


def _clamp(v: float, lo: float, hi: float) -> float:
    """Clamp value between lo and hi"""
    return max(lo, min(hi, v))


def adaptive_mix(
    regime: str,
    confidence: float,
    atr_pct: float,
    pnl_state: str = "normal",
    time_in_pos_min: float = 0.0
) -> Dict[str, Any]:
    """
    Calculate adaptive trading parameters based on market regime and position state.
    
    Args:
        regime: Market regime ("TRENDING", "CHOPPY", "VOLATILE", "SIDEWAYS")
        confidence: Regime detection confidence (0..1)
        atr_pct: ATR as percentage of price
        pnl_state: Current PnL state ("normal", "drawdown", "cooldown")
        time_in_pos_min: Time in position (minutes)
        
    Returns:
        Dict with:
            - sl_atr: SL multiplier for ATR
            - tp_rr: Risk/Reward ratio for TP
            - trail: Enable trailing stop
            - tp_ladder: List of TP level multipliers
    """
    # Base parameters per regime
    base = {
        "TRENDING": {
            "sl_atr": 1.8,
            "tp_rr": 2.3,
            "trail": True,
            "tp_ladder": [1.8, 3.2, 4.8]
        },
        "CHOPPY": {
            "sl_atr": 1.1,
            "tp_rr": 1.5,
            "trail": False,
            "tp_ladder": [1.6, 2.6]
        },
        "VOLATILE": {
            "sl_atr": 2.2,
            "tp_rr": 2.1,
            "trail": True,
            "tp_ladder": [2.0, 3.6]
        },
        "SIDEWAYS": {
            "sl_atr": 1.3,
            "tp_rr": 1.4,
            "trail": False,
            "tp_ladder": [1.4, 2.2]
        }
    }.get(regime, {
        "sl_atr": 1.5,
        "tp_rr": 1.8,
        "trail": False,
        "tp_ladder": [1.6, 2.6]
    })

    # Confidence adjustment: lower confidence = wider SL, less ambitious TP
    k = _clamp(confidence, 0.2, 1.0)
    base["sl_atr"] *= (1.0 + (1.0 - k) * 0.28)  # Lower conf → wider SL
    base["tp_rr"] *= (0.95 + 0.15 * k)           # Higher conf → more ambitious TP

    # Volatility adjustment: higher ATR% = wider SL
    v = _clamp(atr_pct / 100.0, 0.3, 1.2)
    base["sl_atr"] *= (1.0 + (v - 0.6) * 0.35)

    # Apply floors and ceilings
    base["sl_atr"] = _clamp(base["sl_atr"], 0.9, 3.0)
    base["tp_rr"] = _clamp(base["tp_rr"], 1.3, 3.2)

    # PnL state adjustments
    if pnl_state in ("drawdown", "cooldown"):
        base["tp_rr"] *= 0.9    # Less ambitious in drawdown
        base["sl_atr"] *= 0.95  # Tighter SL
        log.info(f"[AdaptiveMixer] PnL state={pnl_state}, reducing risk")

    # Position age adjustments
    if time_in_pos_min > 120:  # Position older than 2 hours
        base["trail"] = True
        log.info(f"[AdaptiveMixer] Position age {time_in_pos_min:.0f}min, enabling trailing")

    log.info(
        f"[AdaptiveMixer] {regime} → sl_atr={base['sl_atr']:.2f}, "
        f"tp_rr={base['tp_rr']:.2f}, trail={base['trail']}, "
        f"tp_ladder={base['tp_ladder']}"
    )

    return base
