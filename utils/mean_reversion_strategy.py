"""
Mean-Reversion Strategy - Deterministic entries for NEUTRAL/low-range markets

Strategy Logic:
- Entry: Price deviates from VWAP by 1.5x ATR
- Exit: Price returns to VWAP (mean reversion)
- High win rate (70-80%) with lower RR (1.05-1.15) acceptable
- Tight risk management with ATR-based stops

Market Conditions:
- CHOPPY/NEUTRAL markets with range <2%
- Low volatility, no clear trend
- Price oscillates around VWAP

Author: AlgoGPT MetaBrain v8.0
"""

from __future__ import annotations
import os
from typing import Dict, Any, Optional, Tuple
from decimal import Decimal
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# Configuration from ENV
VWAP_PERIOD = int(os.getenv("MEAN_REVERSION_VWAP_PERIOD", "50"))  # Rolling VWAP period
ENTRY_ATR_MULT = float(os.getenv("MEAN_REVERSION_ENTRY_ATR", "1.5"))  # Entry deviation from VWAP
EXIT_ATR_MULT = float(os.getenv("MEAN_REVERSION_EXIT_ATR", "1.5"))  # Exit target from VWAP
SL_ATR_MULT = float(os.getenv("MEAN_REVERSION_SL_ATR", "0.7"))  # Stop loss multiplier
MIN_WIN_RATE = float(os.getenv("MEAN_REVERSION_MIN_WIN_RATE", "70.0"))  # Minimum expected win rate
KELTNER_PERIOD = int(os.getenv("MEAN_REVERSION_KELTNER_PERIOD", "20"))
KELTNER_ATR_MULT = float(os.getenv("MEAN_REVERSION_KELTNER_MULT", "2.0"))


def calculate_mean_reversion_levels(
    *,
    price: float,
    df: pd.DataFrame,
    atr_val: float,
    side: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Calculate mean-reversion entry/exit levels using VWAP + Keltner Bands
    
    Args:
        price: Current market price
        df: OHLCV DataFrame with sufficient history
        atr_val: Current ATR value
        side: Optional forced side ("LONG" or "SHORT")
    
    Returns:
        Dictionary with entry, TP levels, SL, RR, and metadata
        None if no valid setup
    """
    try:
        from utils.indicators import vwap, keltner_bands
        
        if df is None or df.empty or len(df) < max(VWAP_PERIOD, KELTNER_PERIOD):
            logger.warning("Insufficient data for mean-reversion calculation")
            return None
        
        if atr_val <= 0:
            logger.warning(f"Invalid ATR: {atr_val}")
            return None
        
        # Calculate VWAP (rolling)
        vwap_series = vwap(df, period=VWAP_PERIOD)
        current_vwap = float(vwap_series.iloc[-1])
        
        if pd.isna(current_vwap) or current_vwap <= 0:
            logger.warning(f"Invalid VWAP: {current_vwap}")
            return None
        
        # Calculate Keltner Bands (for trend confirmation)
        kelt_basis, kelt_upper, kelt_lower = keltner_bands(
            df, 
            period=KELTNER_PERIOD, 
            atr_period=14, 
            multiplier=KELTNER_ATR_MULT
        )
        
        # Current position relative to VWAP
        deviation_pct = ((price - current_vwap) / current_vwap) * 100.0
        deviation_atr = (price - current_vwap) / atr_val
        
        # Determine side based on deviation
        if side is None:
            if deviation_atr < -ENTRY_ATR_MULT:
                side = "LONG"  # Price below VWAP → expect reversion up
            elif deviation_atr > ENTRY_ATR_MULT:
                side = "SHORT"  # Price above VWAP → expect reversion down
            else:
                logger.debug(f"Price too close to VWAP (deviation: {deviation_atr:.2f} ATR)")
                return None
        
        # Calculate levels
        if side == "LONG":
            entry = price
            tp1 = current_vwap + (EXIT_ATR_MULT * atr_val * 0.5)  # Partial at 50% to VWAP
            tp2 = current_vwap + (EXIT_ATR_MULT * atr_val)  # Full at VWAP + buffer
            sl = entry - (SL_ATR_MULT * atr_val)
            
            # Validate setup
            if sl >= entry or tp1 <= entry:
                logger.debug(f"Invalid LONG levels: entry={entry}, tp1={tp1}, sl={sl}")
                return None
            
        else:  # SHORT
            entry = price
            tp1 = current_vwap - (EXIT_ATR_MULT * atr_val * 0.5)
            tp2 = current_vwap - (EXIT_ATR_MULT * atr_val)
            sl = entry + (SL_ATR_MULT * atr_val)
            
            # Validate setup
            if sl <= entry or tp1 >= entry:
                logger.debug(f"Invalid SHORT levels: entry={entry}, tp1={tp1}, sl={sl}")
                return None
        
        # Calculate R:R
        risk = abs(entry - sl)
        reward = abs(tp2 - entry)
        rr = reward / risk if risk > 0 else 0.0
        
        # For mean-reversion, we accept lower RR if win rate is high
        # RR ≥ 1.05 is OK when win rate ≥ 70%
        if rr < 1.05:
            logger.debug(f"RR too low for mean-reversion: {rr:.2f}")
            return None
        
        return {
            "strategy": "mean_reversion",
            "side": side,
            "entry": round(entry, 8),
            "tp1": round(tp1, 8),
            "tp2": round(tp2, 8),
            "sl": round(sl, 8),
            "rr": round(rr, 2),
            "vwap": round(current_vwap, 8),
            "deviation_pct": round(deviation_pct, 3),
            "deviation_atr": round(deviation_atr, 2),
            "atr": round(atr_val, 8),
            "win_rate_expected": MIN_WIN_RATE,
            "quality_score": calculate_quality_score(
                deviation_atr=abs(deviation_atr),
                rr=rr,
                kelt_position=_get_keltner_position(price, kelt_basis.iloc[-1], kelt_upper.iloc[-1], kelt_lower.iloc[-1])
            ),
            "reason": f"Mean-Reversion: Price {deviation_pct:+.2f}% from VWAP, {abs(deviation_atr):.1f}x ATR deviation"
        }
        
    except Exception as e:
        logger.error(f"Mean-reversion calculation failed: {e}", exc_info=True)
        return None


def calculate_quality_score(
    deviation_atr: float,
    rr: float,
    kelt_position: str
) -> float:
    """
    Calculate quality score for mean-reversion setup (0-10 scale)
    
    Factors:
    - Deviation from VWAP (higher = better for mean-reversion)
    - Risk/Reward ratio
    - Position relative to Keltner Bands (extremes = better)
    """
    score = 5.0  # Base score
    
    # Deviation bonus: More deviation = higher probability of reversion
    if deviation_atr >= 2.0:
        score += 2.5  # Strong deviation
    elif deviation_atr >= 1.5:
        score += 1.5  # Good deviation
    else:
        score += 0.5  # Minimal deviation
    
    # R:R bonus
    if rr >= 1.4:
        score += 1.5
    elif rr >= 1.2:
        score += 1.0
    elif rr >= 1.05:
        score += 0.5
    
    # Keltner position bonus (extreme = better)
    if kelt_position in ("below_lower", "above_upper"):
        score += 1.0  # At extremes, high reversion probability
    elif kelt_position in ("near_lower", "near_upper"):
        score += 0.5
    
    return min(max(score, 0.0), 10.0)


def _get_keltner_position(price: float, basis: float, upper: float, lower: float) -> str:
    """Determine price position relative to Keltner Bands"""
    if pd.isna(basis) or pd.isna(upper) or pd.isna(lower):
        return "unknown"
    
    if price < lower:
        return "below_lower"
    elif price > upper:
        return "above_upper"
    elif price < basis - (basis - lower) * 0.5:
        return "near_lower"
    elif price > basis + (upper - basis) * 0.5:
        return "near_upper"
    else:
        return "middle"


def is_mean_reversion_viable(
    market_regime: str,
    range_pct: float,
    volatility: str
) -> bool:
    """
    Check if mean-reversion strategy is viable for current market
    
    Args:
        market_regime: Market regime (CHOPPY, NEUTRAL, etc.)
        range_pct: 24h range percentage
        volatility: Volatility level (low, mid, high)
    
    Returns:
        True if mean-reversion is suitable
    """
    # Mean-reversion works best in:
    # 1. CHOPPY/NEUTRAL markets
    # 2. Range < 2% (too small for GRID)
    # 3. Low to mid volatility
    
    if market_regime not in ("CHOPPY", "NEUTRAL", "SIDEWAYS"):
        return False
    
    if range_pct >= 2.0:
        return False  # Use GRID instead
    
    if volatility == "high":
        return False  # Too volatile for mean-reversion
    
    return True


__all__ = [
    "calculate_mean_reversion_levels",
    "is_mean_reversion_viable",
    "calculate_quality_score"
]
