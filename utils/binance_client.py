# utils/binance_client.py
from __future__ import annotations
import os, logging
from typing import Any, Dict, List, Optional
from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger("algogpt.binance")

# === Load API Keys ===
API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes")

BASE_URL_FUTURES = "https://testnet.binancefuture.com" if TESTNET else "https://fapi.binance.com"

if not API_KEY or not API_SECRET:
    logger.warning("⚠️ Missing Binance API keys")

client = Client(API_KEY, API_SECRET)
client.FUTURES_URL = BASE_URL_FUTURES

# === Safe wrappers ===
def _safe_call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except BinanceAPIException as e:
        logger.error(f"Binance API error: {e.message}")
    except Exception as e:
        logger.error(f"Binance client error: {e}")
    return None

# === Core Futures Helpers ===
def futures_mark_price(symbol: str) -> Optional[float]:
    """Get current mark price"""
    data = _safe_call(client.futures_mark_price, symbol=symbol)
    if not data:
        return None
    return float(data.get("markPrice", 0.0))

def futures_position_risk() -> List[Dict[str, Any]]:
    """Get current open positions"""
    data = _safe_call(client.futures_position_information)
    return data or []

def get_open_orders(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get all open orders (optionally by symbol)"""
    data = _safe_call(client.futures_get_open_orders, symbol=symbol) if symbol else _safe_call(client.futures_get_open_orders)
    return data or []

def cancel_order(symbol: str, order_id: Optional[int] = None, orig_client_order_id: Optional[str] = None) -> Dict[str, Any]:
    """Cancel order by orderId or origClientOrderId"""
    try:
        if order_id:
            return client.futures_cancel_order(symbol=symbol, orderId=order_id)
        elif orig_client_order_id:
            return client.futures_cancel_order(symbol=symbol, origClientOrderId=orig_client_order_id)
    except BinanceAPIException as e:
        logger.error(f"cancel_order API error: {e.message}")
    except Exception as e:
        logger.error(f"cancel_order error: {e}")
    return {}

def fapi_ping() -> bool:
    """Ping Binance Futures API"""
    try:
        client.futures_ping()
        return True
    except Exception:
        return False

def futures_balance() -> List[Dict[str, Any]]:
    """Get Futures account balance"""
    return _safe_call(client.futures_account_balance) or []

def get_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    """Get symbol exchange info"""
    try:
        ex = client.futures_exchange_info()
        for s in ex.get("symbols", []):
            if s.get("symbol") == symbol:
                return s
    except Exception as e:
        logger.error(f"get_symbol_info error: {e}")
    return None

def futures_exchange_info_safe() -> Dict[str, Any]:
    """Safe wrapper for exchange info"""
    return _safe_call(client.futures_exchange_info) or {}













































































































































































