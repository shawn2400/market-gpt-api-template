# utils/binance_client.py
from __future__ import annotations
import os
import logging
from typing import Any, Dict, List, Optional
from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger("algogpt.binance")

# === Load API Keys ===
API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

if not API_KEY or not API_SECRET:
    logger.error("[binance_client] Missing API keys")
    raise RuntimeError("Missing Binance API keys")

# === Init client ===
client = Client(API_KEY, API_SECRET)
client.API_URL = "https://fapi.binance.com/fapi"  # Futures endpoint

# === Defaults for precision fallbacks ===
DEFAULT_QTY_STEP_STR = "0.001"
DEFAULT_PRICE_TICK_STR = "0.01"
DEFAULT_MIN_NOTIONAL = 5.0

# ==================== Core Safe Calls ====================
def fapi_ping() -> bool:
    try:
        client.futures_ping()
        return True
    except Exception as e:
        logger.warning("Futures ping failed: %s", e)
        return False

def futures_exchange_info_safe() -> Optional[Dict[str, Any]]:
    try:
        return client.futures_exchange_info()
    except Exception as e:
        logger.error("Failed to fetch futures_exchange_info: %s", e)
        return None

def futures_balance() -> List[Dict[str, Any]]:
    try:
        return client.futures_account_balance() or []
    except Exception as e:
        logger.error("Failed to fetch futures_balance: %s", e)
        return []

def futures_mark_price(symbol: str) -> Optional[float]:
    try:
        data = client.futures_mark_price(symbol=symbol)
        return float(data["markPrice"])
    except Exception as e:
        logger.error("Failed to fetch mark price for %s: %s", symbol, e)
        return None

def get_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        info = futures_exchange_info_safe()
        if not info:
            return None
        for s in info.get("symbols", []):
            if s.get("symbol") == symbol.upper():
                return s
    except Exception as e:
        logger.error("Failed get_symbol_info: %s", e)
    return None

# ==================== Positions ====================
def get_open_positions(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    מחזיר רשימת פוזיציות פתוחות בחשבון Futures.
    אם מועבר symbol → מסנן לפי סימבול.
    """
    try:
        acc_info = client.futures_account()
        positions = acc_info.get("positions", [])
        out = []
        for pos in positions:
            amt = float(pos.get("positionAmt", "0"))
            if abs(amt) > 1e-12:
                if symbol is None or pos.get("symbol") == symbol.upper():
                    out.append(pos)
        return out
    except Exception as e:
        logger.error("Failed to get open positions: %s", e)
        return []

# ==================== Orders ====================
def futures_create_order(**kwargs) -> Dict[str, Any]:
    """
    יוצר פקודת Futures (Limit / Market / Stop).
    עטיפה בטוחה עם טיפול בשגיאות.
    """
    try:
        return client.futures_create_order(**kwargs)
    except BinanceAPIException as e:
        logger.error("BinanceAPIException: %s", e)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("Failed to create futures order: %s", e)
        return {"ok": False, "error": str(e)}

def set_leverage(symbol: str, leverage: int) -> Dict[str, Any]:
    """
    מגדיר מינוף עבור סימבול מסוים ב-Futures.
    """
    try:
        res = client.futures_change_leverage(symbol=symbol.upper(), leverage=int(leverage))
        return {"ok": True, "data": res}
    except BinanceAPIException as e:
        logger.error("[binance_client] set_leverage BinanceAPIException: %s", e)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("[binance_client] set_leverage failed: %s", e)
        return {"ok": False, "error": str(e)}

__all__ = [
    "fapi_ping",
    "futures_exchange_info_safe",
    "futures_balance",
    "futures_mark_price",
    "get_symbol_info",
    "get_open_positions",
    "futures_create_order",
    "set_leverage",   # ✅ נוסף
    "DEFAULT_QTY_STEP_STR",
    "DEFAULT_PRICE_TICK_STR",
    "DEFAULT_MIN_NOTIONAL",
]

















































































































































































