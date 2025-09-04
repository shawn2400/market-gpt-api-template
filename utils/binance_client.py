# utils/binance_client.py
from __future__ import annotations
import os
import time
import logging
from typing import Any, Dict, List, Optional

from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger("algogpt.binance")

# =============================================================================
# ENV / Client
# =============================================================================
API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
TESTNET = (os.getenv("BINANCE_TESTNET") or "0").strip().lower() in ("1", "true", "yes", "on")

if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing BINANCE_API_KEY / BINANCE_API_SECRET")

client = Client(API_KEY, API_SECRET, testnet=TESTNET)

# =============================================================================
# Caches / Defaults
# =============================================================================
_EXCHANGE_INFO: Dict[str, Any] = {}
_EXCHANGE_INFO_TS: float = 0.0
_EXCHANGE_INFO_TTL: int = int(os.getenv("EXINFO_TTL", "300"))  # seconds

DEFAULT_QTY_STEP_STR: str = "0.001"
DEFAULT_PRICE_TICK_STR: str = "0.01"
DEFAULT_MIN_NOTIONAL: float = 5.0

# =============================================================================
# Exchange Info
# =============================================================================
def _refresh_exchange_info(force_refresh: bool = False) -> Dict[str, Any]:
    global _EXCHANGE_INFO, _EXCHANGE_INFO_TS
    now = time.time()
    if force_refresh or (now - _EXCHANGE_INFO_TS > _EXCHANGE_INFO_TTL) or not _EXCHANGE_INFO:
        try:
            data = client.futures_exchange_info()
            _EXCHANGE_INFO = data or {}
            _EXCHANGE_INFO_TS = now
            logger.info(
                "Binance futures_exchange_info refreshed (symbols=%s)",
                len(_EXCHANGE_INFO.get("symbols", [])),
            )
        except Exception as e:
            logger.error("Failed to refresh exchange info: %s", e)
    return _EXCHANGE_INFO

def futures_exchange_info_safe(force_refresh: bool = False) -> Dict[str, Any]:
    return _refresh_exchange_info(force_refresh=force_refresh)

def get_symbol_info(symbol: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    info = _refresh_exchange_info(force_refresh=force_refresh)
    sy = (symbol or "").upper()
    for s in info.get("symbols", []):
        if s.get("symbol") == sy:
            return s
    return None

def get_symbol_filters(symbol: str) -> Dict[str, Any]:
    info = get_symbol_info(symbol) or {}
    filters = {}
    for f in info.get("filters", []) or []:
        ft = f.get("filterType")
        if ft:
            filters[ft] = f

    tick = (filters.get("PRICE_FILTER", {}) or {}).get("tickSize", DEFAULT_PRICE_TICK_STR)
    step = (filters.get("LOT_SIZE", {}) or {}).get("stepSize", DEFAULT_QTY_STEP_STR)
    min_notional = (
        (filters.get("MIN_NOTIONAL", {}) or {}).get("notional")
        or (filters.get("MIN_NOTIONAL", {}) or {}).get("minNotional")
        or DEFAULT_MIN_NOTIONAL
    )
    return {
        "tickSizeStr": str(tick),
        "stepSizeStr": str(step),
        "minNotional": float(min_notional),
    }

# =============================================================================
# Account / Market Data
# =============================================================================
def fapi_ping() -> bool:
    try:
        client.futures_ping()
        return True
    except Exception as e:
        logger.warning("fapi_ping failed: %s", e)
        return False

def futures_balance() -> Optional[List[Dict[str, Any]]]:
    try:
        return client.futures_account_balance()
    except Exception as e:
        logger.error("futures_balance failed: %s", e)
        return None

def futures_open_positions() -> Optional[List[Dict[str, Any]]]:
    try:
        return client.futures_position_information()
    except Exception as e:
        logger.error("futures_open_positions failed: %s", e)
        return None

def futures_position_risk() -> Optional[List[Dict[str, Any]]]:
    try:
        return client.futures_position_risk()
    except Exception as e:
        logger.error("futures_position_risk failed: %s", e)
        return None

def get_open_orders(symbol: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    try:
        if symbol:
            return client.futures_get_open_orders(symbol=symbol.upper())
        return client.futures_get_open_orders()
    except Exception as e:
        logger.error("get_open_orders failed: %s", e)
        return None

def get_all_orders(symbol: str, limit: int = 100) -> Optional[List[Dict[str, Any]]]:
    try:
        return client.futures_get_all_orders(symbol=symbol.upper(), limit=int(limit))
    except Exception as e:
        logger.error("get_all_orders failed: %s", e)
        return None

def futures_mark_price(symbol: str) -> Optional[float]:
    try:
        res = client.futures_mark_price(symbol=symbol.upper())
        return float(res["markPrice"])
    except Exception as e:
        logger.error("futures_mark_price failed for %s: %s", symbol, e)
        return None

# =============================================================================
# Trading — New Wrappers
# =============================================================================
def place_limit_order(
    *, symbol: str, side: str, quantity: float, price: float,
    time_in_force: str = "GTC", post_only: bool = False,
    reduce_only: bool = False, position_side: Optional[str] = None,
    new_client_order_id: Optional[str] = None
) -> Dict[str, Any]:
    try:
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "LIMIT",
            "timeInForce": time_in_force,
            "quantity": quantity,
            "price": price,
        }
        if reduce_only:
            params["reduceOnly"] = True
        if post_only:
            params["timeInForce"] = "GTX"
        if position_side:
            params["positionSide"] = position_side
        if new_client_order_id:
            params["newClientOrderId"] = new_client_order_id

        return client.futures_create_order(**params)
    except BinanceAPIException as e:
        logger.error("BinanceAPIException (place_limit_order): %s", e)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("place_limit_order failed: %s", e)
        return {"ok": False, "error": str(e)}

def place_stop_market_order(
    *, symbol: str, side: str, stop_price: float,
    quantity: Optional[float] = None, reduce_only: bool = True,
    position_side: Optional[str] = None, new_client_order_id: Optional[str] = None
) -> Dict[str, Any]:
    try:
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "STOP_MARKET",
            "stopPrice": stop_price,
        }
        if quantity:
            params["quantity"] = quantity
        if reduce_only:
            params["reduceOnly"] = True
        if position_side:
            params["positionSide"] = position_side
        if new_client_order_id:
            params["newClientOrderId"] = new_client_order_id

        return client.futures_create_order(**params)
    except BinanceAPIException as e:
        logger.error("BinanceAPIException (place_stop_market_order): %s", e)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("place_stop_market_order failed: %s", e)
        return {"ok": False, "error": str(e)}

def place_take_profit_market(
    *, symbol: str, side: str, stop_price: float,
    quantity: Optional[float] = None, reduce_only: bool = True,
    position_side: Optional[str] = None, new_client_order_id: Optional[str] = None
) -> Dict[str, Any]:
    try:
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "TAKE_PROFIT_MARKET",
            "stopPrice": stop_price,
        }
        if quantity:
            params["quantity"] = quantity
        if reduce_only:
            params["reduceOnly"] = True
        if position_side:
            params["positionSide"] = position_side
        if new_client_order_id:
            params["newClientOrderId"] = new_client_order_id

        return client.futures_create_order(**params)
    except BinanceAPIException as e:
        logger.error("BinanceAPIException (place_take_profit_market): %s", e)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("place_take_profit_market failed: %s", e)
        return {"ok": False, "error": str(e)}

# =============================================================================
# Trading settings
# =============================================================================
def set_leverage(symbol: str, leverage: int) -> Dict[str, Any]:
    try:
        res = client.futures_change_leverage(symbol=symbol.upper(), leverage=int(leverage))
        return {"ok": True, "result": res}
    except BinanceAPIException as e:
        logger.error("BinanceAPIException (set_leverage): %s", e)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("set_leverage failed: %s", e)
        return {"ok": False, "error": str(e)}

def get_futures_client() -> Client:
    return client

# =============================================================================
# Compatibility shims
# =============================================================================
def get_open_positions():
    try:
        return futures_open_positions()
    except Exception:
        return []

def get_futures_open_positions():
    try:
        return futures_open_positions()
    except Exception:
        return []

def get_signed_balance():
    try:
        return futures_balance()
    except Exception:
        return []

def get_mark_price(symbol: str):
    try:
        return futures_mark_price(symbol)
    except Exception:
        return None

def exchange_info_safe(force_refresh: bool = False):
    try:
        return futures_exchange_info_safe(force_refresh=force_refresh)
    except Exception:
        return {"symbols": []}

# =============================================================================
# Public API
# =============================================================================
__all__ = [
    "get_futures_client", "set_leverage",
    "futures_exchange_info_safe", "get_symbol_info", "get_symbol_filters",
    "fapi_ping", "futures_balance", "futures_open_positions", "futures_position_risk",
    "get_open_orders", "get_all_orders", "futures_mark_price",
    "place_limit_order", "place_stop_market_order", "place_take_profit_market",
    "get_open_positions", "get_futures_open_positions", "get_signed_balance",
    "get_mark_price", "exchange_info_safe",
]














































































































































































