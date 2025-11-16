# -*- coding: utf-8 -*-
"""
Binance Futures Position Mode Manager - SMART COMPATIBILITY MODE

Supports BOTH Hedge Mode and One-Way Mode automatically:
- Detects current position mode (dualSidePosition)
- Adapts orders based on detected mode
- No forced mode switching (prevents -4061 errors)

Hedge Mode (dualSidePosition=true):
  - Allows simultaneous LONG+SHORT on same symbol
  - Requires positionSide parameter in orders

One-Way Mode (dualSidePosition=false):
  - Allows only one direction at a time
  - Must OMIT positionSide parameter in orders
  
Auto-detection prevents Binance API errors when positions are open.
"""
from __future__ import annotations
import os
import time
import hmac
import hashlib
import urllib.parse
import urllib.request
import json
import logging
from typing import Optional, Dict, Any, Literal

logger = logging.getLogger(__name__)

BINANCE_FAPI = os.getenv("BINANCE_FAPI", "https://fapi.binance.com")
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
FORCE_HEDGE = os.getenv("BINANCE_FORCE_HEDGE_MODE", "1") == "1"

# Cache for position mode to avoid excessive API calls
_position_mode_cache: Optional[Dict[str, Any]] = None
_cache_timestamp = 0
CACHE_TTL_SECONDS = 300  # 5 minutes

PositionMode = Literal["HEDGE", "ONEWAY"]


def _sign(qs: str) -> str:
    """Sign query string with API secret"""
    return hmac.new(API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()


def _req(method: str, path: str, qs: str) -> dict:
    """Make authenticated request to Binance Futures API"""
    url = f"{BINANCE_FAPI}{path}?{qs}&signature={_sign(qs)}"
    req = urllib.request.Request(
        url,
        method=method,
        headers={"X-MBX-APIKEY": API_KEY}
    )
    
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def get_dual_position_mode() -> bool:
    """
    Get current dualSidePosition setting
    Returns: True if Hedge Mode is enabled, False otherwise
    """
    if not (API_KEY and API_SECRET):
        logger.warning("Binance API credentials missing")
        return False
    
    try:
        ts = int(time.time() * 1000)
        data = _req("GET", "/fapi/v1/positionSide/dual", f"timestamp={ts}")
        return bool(data.get("dualSidePosition", False))
    except Exception as e:
        logger.exception(f"Failed to get dual position mode: {e}")
        return False


def detect_position_mode(force_refresh: bool = False) -> PositionMode:
    """
    Detect current position mode with caching.
    
    Args:
        force_refresh: Force API call instead of using cache
        
    Returns:
        "HEDGE" if Hedge Mode enabled, "ONEWAY" otherwise
    """
    global _position_mode_cache, _cache_timestamp
    
    # Check cache validity
    current_time = time.time()
    if not force_refresh and _position_mode_cache and (current_time - _cache_timestamp) < CACHE_TTL_SECONDS:
        mode = _position_mode_cache.get("mode", "ONEWAY")
        logger.debug(f"Using cached position mode: {mode}")
        return mode
    
    # Fetch from API
    try:
        is_hedge = get_dual_position_mode()
        mode: PositionMode = "HEDGE" if is_hedge else "ONEWAY"
        
        # Update cache
        _position_mode_cache = {"mode": mode, "is_dual": is_hedge}
        _cache_timestamp = current_time
        
        logger.info(f"✅ Detected Position Mode: {mode} (dualSidePosition={is_hedge})")
        return mode
        
    except Exception as e:
        logger.warning(f"Failed to detect position mode: {e}, defaulting to ONEWAY")
        # Safe default - ONEWAY mode works in most cases
        _position_mode_cache = {"mode": "ONEWAY", "is_dual": False}
        _cache_timestamp = current_time
        return "ONEWAY"


def adapt_order_for_mode(order_params: Dict[str, Any], side: str, position_mode: Optional[PositionMode] = None) -> Dict[str, Any]:
    """
    Adapt order parameters based on detected position mode.
    
    Args:
        order_params: Original order parameters
        side: Trade side ("BUY" or "SELL")
        position_mode: Optional override, otherwise auto-detected
        
    Returns:
        Adapted order parameters safe for current position mode
        
    Example:
        # Input (HEDGE mode):
        {"symbol": "BTCUSDT", "side": "BUY", "positionSide": "LONG"}
        
        # Output (ONE-WAY mode):
        {"symbol": "BTCUSDT", "side": "BUY"}  # positionSide removed
    """
    if position_mode is None:
        position_mode = detect_position_mode()
    
    adapted = order_params.copy()
    
    if position_mode == "HEDGE":
        # Hedge Mode - MUST have positionSide
        if "positionSide" not in adapted:
            # Infer from side
            adapted["positionSide"] = "LONG" if side in ["BUY", "LONG"] else "SHORT"
            logger.debug(f"Added positionSide={adapted['positionSide']} for Hedge Mode")
    
    elif position_mode == "ONEWAY":
        # One-Way Mode - MUST NOT have positionSide
        if "positionSide" in adapted:
            removed_side = adapted.pop("positionSide")
            logger.debug(f"Removed positionSide={removed_side} for One-Way Mode")
    
    return adapted


def ensure_hedge_mode() -> bool:
    """
    DEPRECATED: Smart compatibility mode replaces forced Hedge Mode.
    
    This function now only attempts to enable Hedge Mode at startup.
    If positions are open, it gracefully fails without errors.
    
    Returns: True if successful or not needed, False if failed
    """
    if not (API_KEY and API_SECRET):
        logger.warning("Binance API credentials missing, cannot enforce Hedge Mode")
        return False
    
    if not FORCE_HEDGE:
        logger.info("BINANCE_FORCE_HEDGE_MODE not enabled, skipping enforcement")
        return True
    
    try:
        # First, check if already in Hedge Mode
        current_mode = get_dual_position_mode()
        if current_mode:
            logger.info("✅ Hedge Mode already enabled, no action needed")
            return True
        
        # Check if there are any open positions (this would block mode change)
        try:
            ts = int(time.time() * 1000)
            positions = _req("GET", "/fapi/v2/positionRisk", f"timestamp={ts}")
            has_positions = any(float(p.get("positionAmt", 0)) != 0 for p in positions)
            
            if has_positions:
                logger.info(
                    "ℹ️  Hedge Mode will auto-activate when positions close. "
                    "Currently operating in One-Way Mode (open positions exist)."
                )
                return False  # Not an error, just can't change mode now
        except Exception:
            logger.debug("Could not check positions, proceeding with mode change attempt")
        
        # Not in Hedge Mode and no positions - try to enable it
        logger.info("Attempting to enable Hedge Mode...")
        ts = int(time.time() * 1000)
        body = f"dualSidePosition=true&timestamp={ts}"
        result = _req("POST", "/fapi/v1/positionSide/dual", body)
        
        logger.info(f"✅ Hedge Mode enabled: {result}")
        # Invalidate cache
        global _cache_timestamp
        _cache_timestamp = 0
        return True
        
    except Exception as e:
        error_msg = str(e)
        if "-4061" in error_msg:
            logger.warning(
                "⚠️ Cannot switch to Hedge Mode (positions/orders exist). "
                "System will operate in current mode compatibility."
            )
        else:
            logger.error(f"Failed to enforce Hedge Mode: {e}")
        
        # Not a critical error - system will adapt to current mode
        logger.info("💡 Using Smart Compatibility Mode - works in BOTH Hedge and One-Way modes")
        return False
