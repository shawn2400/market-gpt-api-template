# -*- coding: utf-8 -*-
"""
Binance Hedge Mode Enforcement Module
Ensures dualSidePosition=true for proper LONG/SHORT separation
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

logger = logging.getLogger(__name__)

BINANCE_FAPI = os.getenv("BINANCE_FAPI", "https://fapi.binance.com")
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
FORCE_HEDGE = os.getenv("BINANCE_FORCE_HEDGE_MODE", "1") == "1"


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


def ensure_hedge_mode() -> bool:
    """
    Ensure Hedge Mode (dualSidePosition=true) is enabled
    Returns: True if successful, False otherwise
    """
    if not (API_KEY and API_SECRET):
        logger.warning("Binance API credentials missing, cannot enforce Hedge Mode")
        return False
    
    if not FORCE_HEDGE:
        logger.info("BINANCE_FORCE_HEDGE_MODE not enabled, skipping enforcement")
        return True
    
    try:
        ts = int(time.time() * 1000)
        body = f"dualSidePosition=true&timestamp={ts}"
        result = _req("POST", "/fapi/v1/positionSide/dual", body)
        
        logger.info(f"Hedge Mode enforced: {result}")
        return True
        
    except Exception as e:
        logger.exception(f"Failed to enforce Hedge Mode: {e}")
        return False
