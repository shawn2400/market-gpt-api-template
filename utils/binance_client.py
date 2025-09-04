# utils/binance_client.py
from __future__ import annotations
import os
import logging
from typing import Any, Dict, Optional, List
from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger("algogpt.binance")

# === Load API Keys ===
API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

if not API_KEY or not API_SECRET:
    logger.warning("⚠️ Binance API keys missing or empty")

# === Binance Client ===
_client: Optional[Client] = None

def get_client() -> Client:
    """Lazy init Binance client"""
    global _client
    if _client is None:
        _client = Client(API_KEY, API_SECRET)
    return _client

# === Default Fallbacks ===
DEFAULT_QTY_STEP_STR = "0.001"
DEFAULT_PRICE_TICK_STR = "0.01"
DEFAULT_MIN_NOTIONAL = 5.0

# === API Helpers ===
def fapi_ping() -> bool:
    try:
        get_client().futures_ping()
        return True
    except Exception as e:
        logger.error(f"[binance_client] futures_ping failed: {e}")
        return False

def futures_exchange_info_safe() -> Optional[Dict[str, Any]]:
    """Fetch futures exchangeInfo safely"""
    try:
        return get_client().futures_exchange_info()
    except Exception as e:
        logger.error(f"[binance_client] exchange_info failed: {e}")
        return None

def futures_mark_price(symbol: str) -> Optional[float]:
    try:
        data = get_client().futures_mark_price(symbol=symbol)
        return float(data["markPrice"])
    except Exception as e:
        logger.error(f"[binance_client] futures_mark_price failed for {symbol}: {e}")
        return None

def futures_balance() -> List[Dict[str, Any]]:
    try:
        return get_client().futures_account_balance()
    except Exception as e:
        logger.error(f"[binance_client] futures_balance failed: {e}")
        return []

def futures_open_positions() -> List[Dict[str, Any]]:
    try:
        return get_client().futures_position_information()
    except Exception as e:
        logger.error(f"[binance_client] futures_open_positions failed: {e}")
        return []

def get_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    """Return exchangeInfo for a specific symbol"""
    info = futures_exchange_info_safe()
    if not info:
        return None
    for s in info.get("symbols", []):
        if s.get("symbol") == symbol.upper():
            return s
    return None

# === Order Ops ===
def cancel_order(symbol: str, order_id: int) -> bool:
    try:
        get_client().futures_cancel_order(symbol=symbol, orderId=order_id)
        return True
    except BinanceAPIException as e:
        logger.error(f"[binance_client] cancel_order failed for {symbol} {order_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"[binance_client] cancel_order unexpected error: {e}")
        return False

# === Wrapper for compatibility ===
from utils.precision_utils import _symbol_filters

def get_symbol_filters(symbol: str) -> Dict[str, Any]:
    """
    Wrapper around precision_utils._symbol_filters
    Ensures compatibility for order_hygiene and others.
    """
    return _symbol_filters(symbol)

__all__ = [
    "get_client",
    "fapi_ping",
    "futures_exchange_info_safe",
    "futures_mark_price",
    "futures_balance",
    "futures_open_positions",
    "get_symbol_info",
    "cancel_order",
    "get_symbol_filters",
    "DEFAULT_QTY_STEP_STR",
    "DEFAULT_PRICE_TICK_STR",
    "DEFAULT_MIN_NOTIONAL",
]














































































































































































