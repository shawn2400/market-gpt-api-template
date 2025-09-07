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
# שימוש ב-Futures; השורה הזאת בסדר אם אתם עובדים על UM Futures בלבד
client.API_URL = "https://fapi.binance.com/fapi"

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

# alias תאימות ל-routes שמצפים לשם 'exchange_info'
def exchange_info() -> Dict[str, Any]:
    info = futures_exchange_info_safe() or {}
    return info if isinstance(info, dict) else {}

def futures_balance() -> List[Dict[str, Any]]:
    try:
        return client.futures_account_balance() or []
    except Exception as e:
        logger.error("Failed to fetch futures_balance: %s", e)
        return []

def futures_mark_price(symbol: str) -> Optional[float]:
    try:
        data = client.futures_mark_price(symbol=symbol.upper())
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

def get_symbol_filters(symbol: str) -> Optional[Dict[str, Any]]:
    """
    מחלץ פילטרים (minQty, tickSize, minNotional) עבור סימבול נתון.
    """
    try:
        info = get_symbol_info(symbol)
        if not info:
            return None
        filters = {}
        for f in info.get("filters", []):
            ftype = f.get("filterType")
            if ftype == "LOT_SIZE":
                filters["minQty"] = f.get("minQty")
                filters["stepSize"] = f.get("stepSize")
            elif ftype == "PRICE_FILTER":
                filters["tickSize"] = f.get("tickSize")
            elif ftype == "MIN_NOTIONAL":
                filters["minNotional"] = f.get("notional") or f.get("minNotional")
        return filters
    except Exception as e:
        logger.error("Failed get_symbol_filters: %s", e)
        return None

# ==================== Positions ====================
def get_open_positions(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    מחזיר רשימת פוזיציות פתוחות בחשבון Futures.
    אם מועבר symbol → מסנן לפי סימבול.
    """
    try:
        acc_info = client.futures_account()
        positions = acc_info.get("positions", []) or []
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

# תאימות ל-routes שמבקשים פונקציה בשם הזו
def futures_open_positions_safe(symbol: Optional[str] = None) -> List[dict]:
    try:
        return get_open_positions(symbol)
    except Exception:
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

def futures_cancel_all_orders(symbol: str) -> Dict[str, Any]:
    """
    מבטל את כל ההוראות הפתוחות לסימבול מסוים.
    """
    try:
        return client.futures_cancel_all_open_orders(symbol=symbol.upper())
    except Exception as e:
        logger.error("Failed to cancel orders for %s: %s", symbol, e)
        return {"ok": False, "error": str(e)}

def get_open_orders(symbol: Optional[str] = None) -> List[dict]:
    """
    תאימות ל-routes.orders: מחזיר הזמנות פתוחות (אם יש), אחרת רשימה ריקה.
    """
    try:
        if symbol:
            return client.futures_get_open_orders(symbol=symbol.upper()) or []
        return client.futures_get_open_orders() or []
    except Exception as e:
        logger.warning("get_open_orders failed: %s", e)
        return []

# ==================== Leverage ====================
def set_leverage(symbol: str, leverage: int) -> Dict[str, Any]:
    """
    קובע מינוף חדש לסימבול נתון.
    """
    try:
        return client.futures_change_leverage(symbol=symbol.upper(), leverage=int(leverage))
    except Exception as e:
        logger.error("Failed to set leverage %s for %s: %s", leverage, symbol, e)
        return {"ok": False, "error": str(e)}

# ==================== Convenience / Shims ====================
def get_futures_client() -> Client:
    """
    תאימות ל-routes.grid ורבות אחרות: מחזיר מופע client לשימוש מתקדם.
    """
    return client

def get_price(symbol: str) -> Optional[float]:
    """
    מחיר עדכני:
    1) קודם מנסה קאש WS (אם utils.ws_fallback קיים)
    2) אחרת futures_mark_price (REST)
    """
    try:
        from utils.ws_fallback import get_price as _ws_get_price  # type: ignore
        px = _ws_get_price(symbol)
        if px:
            return float(px)
    except Exception:
        pass
    return futures_mark_price(symbol)

__all__ = [
    "fapi_ping",
    "futures_exchange_info_safe",
    "exchange_info",
    "futures_balance",
    "futures_mark_price",
    "get_symbol_info",
    "get_symbol_filters",
    "get_open_positions",
    "futures_open_positions_safe",
    "get_open_orders",
    "futures_create_order",
    "futures_cancel_all_orders",
    "set_leverage",
    "get_futures_client",
    "get_price",
    "DEFAULT_QTY_STEP_STR",
    "DEFAULT_PRICE_TICK_STR",
    "DEFAULT_MIN_NOTIONAL",
]


















































































































































































