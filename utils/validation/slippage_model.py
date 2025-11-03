# utils/validation/slippage_model.py
"""
Empirical Slippage Model
========================
Estimates realistic slippage based on historical execution data.
"""

from __future__ import annotations
import os
import logging
from typing import Optional, Dict, Any
import json

logger = logging.getLogger("validation.slippage")

try:
    from utils.db import get_slippage, upsert_slippage, get_all_slippage
    DB_AVAILABLE = True
except ImportError:
    logger.warning("Database functions not available for slippage model")
    DB_AVAILABLE = False

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
    Load historical slippage data from database (or fallback to file).
    
    Returns:
        Dict mapping (symbol, side, vol_regime) to slippage stats
    """
    if DB_AVAILABLE:
        try:
            return get_all_slippage()
        except Exception as e:
            logger.error(f"Failed to load slippage from database: {e}")
    
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
            logger.info(f"Loaded slippage history from JSON file: {filepath}")
            return data
    except FileNotFoundError:
        logger.warning(f"Slippage history file not found: {filepath}")
        return {}
    except Exception as e:
        logger.error(f"Failed to load slippage history: {e}")
        return {}

def save_slippage_data(symbol: str, side: str, vol_regime: str, avg_slippage_bps: float, sample_count: int):
    """
    Save slippage data to database.
    
    Args:
        symbol: Trading symbol
        side: LONG or SHORT
        vol_regime: LOW, MEDIUM, HIGH
        avg_slippage_bps: Average slippage in basis points
        sample_count: Number of samples
    """
    if not DB_AVAILABLE:
        logger.warning("Database not available, cannot save slippage data")
        return
    
    try:
        upsert_slippage(symbol, side, vol_regime, avg_slippage_bps, sample_count)
        logger.info(f"Saved slippage data: {symbol} {side} {vol_regime} = {avg_slippage_bps}bps (n={sample_count})")
    except Exception as e:
        logger.error(f"Failed to save slippage data: {e}")

def migrate_slippage_from_json(filepath: str = "data/slippage_history.json"):
    """
    Migrate slippage data from JSON file to database.
    
    Args:
        filepath: Path to JSON file
    """
    if not DB_AVAILABLE:
        logger.error("Database not available, cannot migrate slippage data")
        return
    
    if not os.path.exists(filepath):
        logger.info(f"No JSON file to migrate: {filepath}")
        return
    
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
        
        migrated = 0
        for key, value in data.items():
            symbol = value.get("symbol")
            side = value.get("side")
            vol_regime = value.get("vol_regime")
            avg_slippage_bps = value.get("avg_slippage_bps")
            sample_count = value.get("sample_count", 0)
            
            if all([symbol, side, vol_regime, avg_slippage_bps is not None]):
                upsert_slippage(symbol, side, vol_regime, avg_slippage_bps, sample_count)
                migrated += 1
        
        logger.info(f"Migrated {migrated} slippage records from {filepath} to database")
        
        backup_path = filepath + ".migrated"
        os.rename(filepath, backup_path)
        logger.info(f"Renamed {filepath} to {backup_path}")
        
    except Exception as e:
        logger.error(f"Failed to migrate slippage data: {e}")
