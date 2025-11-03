# utils/validation/slippage_model.py
"""
Empirical Slippage Model
========================
Estimates realistic slippage based on historical execution data.
"""

from __future__ import annotations
import os
import logging
from typing import Optional
import json

logger = logging.getLogger("validation.slippage")

def estimate_slippage(
    symbol: str,
    side: str,
    timestamp: Optional[int] = None,
    *,
    vol_regime: str = "normal",
) -> float:
    """
    Estimate realistic slippage for a trade.
    
    Args:
        symbol: Trading symbol
        side: LONG or SHORT
        timestamp: Unix timestamp (optional)
        vol_regime: Volatility regime (normal/high/extreme)
        
    Returns:
        Estimated slippage in percentage
    """
    # Load slippage configuration
    slippage_pctl = float(os.getenv("SLIPPAGE_PCTL", "0.75"))
    
    # Base slippage by symbol tier
    base_slippage = _get_base_slippage(symbol)
    
    # Volatility adjustment
    vol_multiplier = {
        "normal": 1.0,
        "high": 1.5,
        "extreme": 2.5,
    }.get(vol_regime, 1.0)
    
    # Calculate final slippage
    slippage_pct = base_slippage * vol_multiplier
    
    # Cap at reasonable maximum
    max_slippage = float(os.getenv("MAX_SLIPPAGE_PCT", "0.5"))  # 0.5% default
    slippage_pct = min(slippage_pct, max_slippage)
    
    logger.debug(f"Slippage estimate for {symbol}: {slippage_pct:.4f}% (regime={vol_regime})")
    
    return slippage_pct

def _get_base_slippage(symbol: str) -> float:
    """
    Get base slippage for symbol based on tier/liquidity.
    
    Tier 1 (BTC, ETH, BNB): 0.01-0.02%
    Tier 2 (Top 20): 0.02-0.05%
    Tier 3 (Others): 0.05-0.10%
    """
    # Load custom slippage map if available
    slippage_map_raw = os.getenv("SLIPPAGE_MAP_JSON", "")
    if slippage_map_raw:
        try:
            slippage_map = json.loads(slippage_map_raw)
            if symbol in slippage_map:
                return float(slippage_map[symbol])
        except Exception as e:
            logger.warning(f"Failed to parse SLIPPAGE_MAP_JSON: {e}")
    
    # Default tiers
    tier1 = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    tier2 = ["SOLUSDT", "ADAUSDT", "XRPUSDT", "DOGEUSDT", "DOTUSDT", 
             "MATICUSDT", "AVAXUSDT", "LINKUSDT", "UNIUSDT", "LTCUSDT"]
    
    if symbol in tier1:
        return 0.015  # 0.015% for high liquidity
    elif symbol in tier2:
        return 0.035  # 0.035% for medium liquidity
    else:
        return 0.075  # 0.075% for lower liquidity

def load_historical_slippage(filepath: str = "data/slippage_history.json") -> dict:
    """
    Load historical slippage data from file.
    
    Returns:
        Dict mapping (symbol, side, vol_regime) to slippage stats
    """
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"Slippage history file not found: {filepath}")
        return {}
    except Exception as e:
        logger.error(f"Failed to load slippage history: {e}")
        return {}
