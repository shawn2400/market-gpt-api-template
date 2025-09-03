# utils/binance_client.py
from __future__ import annotations

import os, time, logging
from typing import Any, Dict, List, Optional
from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger("algogpt.binance")

# === Load API Keys ===
API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
TESTNET = str(os.getenv("BINANCE_TESTNET", "0")).lower() in ("1", "true", "yes")

if not API_KEY or not API_SECRET:
    raise RuntimeError("❌ Missing BINANCE_API_KEY / BINANCE_API_SECRET")

client = Client(API_KEY, API_SECRET, testnet=TESTNET)

# === Caches ===
_EXCHANGE_INFO: Dict[str, Any] = {}
_EXCHANGE_INFO_TS: float = 0.0
_EXCHANGE_INFO_TTL: int = 300  # 5 minutes


# === Helpers ===
def _refresh_exchange_info(force_refresh: bool = False) -> Dict[str, Any]:
    global _EXCHANGE_INFO, _EXCHANGE_INFO_TS
    now = time.time()
    if force_refresh or (now - _EXCHANGE_INFO_TS > _EXCHANGE_INFO_TTL):
        try:
            data = client.futures_exchange_info()
            _EXCHANGE_INFO = data
            _EXCHANGE_INFO_TS = now
            logger.info("Binance futures_exchange_info refreshed")
        except Exception as e:
            logger.error(f"Failed to refresh exchange info: {e}")
    return _EXCHANGE_INFO


# === Core Functions ===
def fapi_ping() -> bool:
    try:
        client.futures_ping()
        return True
    except Exception as e:
        logger.warning(f"fapi_ping failed: {e}")
        return False


def futures_balance() -> Optional[List[Dict[str, Any]]]:
    try:
        return client.futures_account_balance()
    except Exception as e:
        logger.error(f"futures_balance failed: {e}")
        return None


def futures_open_positions() -> Optional[List[Dict[str, Any]]]:
    try:
        return client.futures_position_information()
    except Exception as e:
        logger.error(f"futures_open_positions failed: {e}")
        return None


def futures_mark_price(symbol: str) -> Optional[float]:
    try:
        res = client.futures_mark_price(symbol=symbol.upper())
        return float(res["markPrice"])
    except Exception as e:
        logger.error(f"futures_mark_price failed for {symbol}: {e}")
        return None


def futures_exchange_info_safe(force_refresh: bool = False) -> Dict[str, Any]:
    return _refresh_exchange_info(force_refresh=force_refresh)


def get_symbol_info(symbol: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    info = _refresh_exchange_info(force_refresh=force_refresh)
    syms = info.get("symbols", [])
    symbol = symbol.upper()
    for s in syms:
        if s.get("symbol") == symbol:
            return s
    return None


# === Order Functions (basic) ===
def place_limit_order(
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    reduce_only: bool = False,
    time_in_force: str = "GTC",
) -> Dict[str, Any]:
    """
    Place a limit order on Binance Futures
    """
    try:
        order = client.futures_create_order(
            symbol=symbol.upper(),
            side=side.upper(),
            type="LIMIT",
            quantity=quantity,
            price=price,
            timeInForce=time_in_force,
            reduceOnly=reduce_only,
        )
        logger.info(f"Limit order placed: {order}")
        return {"ok": True, "order": order}
    except BinanceAPIException as e:
        logger.error(f"BinanceAPIException: {e}")
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error(f"place_limit_order failed: {e}")
        return {"ok": False, "error": str(e)}


def cancel_order(symbol: str, order_id: int) -> Dict[str, Any]:
    try:
        res = client.futures_cancel_order(symbol=symbol.upper(), orderId=order_id)
        return {"ok": True, "result": res}
    except Exception as e:
        logger.error(f"cancel_order failed: {e}")
        return {"ok": False, "error": str(e)}







































































































































































