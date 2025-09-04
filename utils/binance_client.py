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

DEFAULT_QTY_STEP_STR: str = "0.001"
DEFAULT_PRICE_TICK_STR: str = "0.01"
DEFAULT_MIN_NOTIONAL: float = 5.0

# --------------------------------------------------------------------
# Exchange Info
# --------------------------------------------------------------------
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

def futures_exchange_info_safe(force_refresh: bool = False) -> Dict[str, Any]:
    return _refresh_exchange_info(force_refresh=force_refresh)

def get_symbol_info(symbol: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    info = _refresh_exchange_info(force_refresh=force_refresh)
    for s in info.get("symbols", []):
        if s.get("symbol") == symbol.upper():
            return s
    return None

def get_symbol_filters(symbol: str) -> Dict[str, Any]:
    info = get_symbol_info(symbol) or {}
    filters = {f["filterType"]: f for f in info.get("filters", [])}

    tick = filters.get("PRICE_FILTER", {}).get("tickSize", DEFAULT_PRICE_TICK_STR)
    step = filters.get("LOT_SIZE", {}).get("stepSize", DEFAULT_QTY_STEP_STR)
    min_notional = (
        filters.get("MIN_NOTIONAL", {}).get("notional")
        or filters.get("MIN_NOTIONAL", {}).get("minNotional")
        or DEFAULT_MIN_NOTIONAL
    )

    return {
        "tickSizeStr": str(tick),
        "stepSizeStr": str(step),
        "minNotional": float(min_notional),
    }

# --------------------------------------------------------------------
# Account
# --------------------------------------------------------------------
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

def futures_position_risk() -> Optional[List[Dict[str, Any]]]:
    try:
        return client.futures_position_risk()
    except Exception as e:
        logger.error(f"futures_position_risk failed: {e}")
        return None

def get_open_orders(symbol: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    try:
        if symbol:
            return client.futures_get_open_orders(symbol=symbol.upper())
        return client.futures_get_open_orders()
    except Exception as e:
        logger.error(f"get_open_orders failed: {e}")
        return None

def get_all_orders(symbol: str, limit: int = 100) -> Optional[List[Dict[str, Any]]]:
    try:
        return client.futures_get_all_orders(symbol=symbol.upper(), limit=limit)
    except Exception as e:
        logger.error(f"get_all_orders failed: {e}")
        return None

def futures_mark_price(symbol: str) -> Optional[float]:
    try:
        res = client.futures_mark_price(symbol=symbol.upper())
        return float(res["markPrice"])
    except Exception as e:
        logger.error(f"futures_mark_price failed for {symbol}: {e}")
        return None

# --------------------------------------------------------------------
# Orders (place_limit_order, cancel_order וכו' נשארים כמו אצלך)
# --------------------------------------------------------------------

# --------------------------------------------------------------------
# Leverage
# --------------------------------------------------------------------
def set_leverage(symbol: str, leverage: int) -> Dict[str, Any]:
    try:
        res = client.futures_change_leverage(symbol=symbol.upper(), leverage=int(leverage))
        return {"ok": True, "result": res}
    except BinanceAPIException as e:
        logger.error(f"BinanceAPIException (set_leverage): {e}")
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error(f"set_leverage failed: {e}")
        return {"ok": False, "error": str(e)}

def get_futures_client() -> Client:
    return client













































































































































































