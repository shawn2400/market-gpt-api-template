# utils/binance_client.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, math, logging, threading
from contextlib import suppress
from typing import Any, Dict, List, Optional, Tuple, cast
from dotenv import load_dotenv

load_dotenv()

from utils.metrics_tracker import observe_http, observe_http_ctx  # מדידת לטנסי/HTTP

logger = logging.getLogger("algogpt.binance")

try:
    from binance.client import Client  # type: ignore
    from binance.exceptions import BinanceAPIException  # type: ignore
    _BINANCE_AVAILABLE = True
except Exception as _e:
    Client = object  # type: ignore

    class BinanceAPIException(Exception):  # type: ignore
        pass

    _BINANCE_AVAILABLE = False
    logger.warning("[binance_client] python-binance not installed (%s) — running in stub mode", _e)

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
if not API_KEY or not API_SECRET:
    logger.warning("[binance_client] Missing API keys (BINANCE_API_KEY/SECRET). Client will stay lazy-uninitialized.")

HTTP_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "10.0"))
WORKING_TYPE = os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE").upper()
RECV_WINDOW = int(os.getenv("BINANCE_RECV_WINDOW", os.getenv("BINANCE_RECV_WINDOW_MS", "15000")))

EXINFO_TTL = int(os.getenv("EXCHANGE_INFO_TTL_SEC", "900"))
ORD_BUCKET_WINDOW = int(os.getenv("ORDERS_BUCKET_WINDOW_SEC", "10"))
ORD_QPS_BUCKET = int(os.getenv("ORDERS_QPS_BUCKET", "4"))
BACKOFF_BASE_MS = int(os.getenv("ORDER_BACKOFF_BASE_MS", "120"))
BACKOFF_MAX_MS = int(os.getenv("ORDER_BACKOFF_MAX_MS", "1600"))
BINANCE_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "2"))

DEFAULT_QTY_STEP_STR = os.getenv("DEFAULT_QTY_STEP", "0.001")
DEFAULT_PRICE_TICK_STR = os.getenv("DEFAULT_PRICE_TICK", "0.01")
DEFAULT_MIN_NOTIONAL = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

PERCENT_GUARD_ENABLE = os.getenv("PERCENT_GUARD_ENABLE", "1").lower() in ("1", "true", "yes", "on")
PERCENT_GUARD_BPS = int(os.getenv("PERCENT_PRICE_GUARD_BPS", os.getenv("PERCENT_GUARD_BPS", "50")))

IDEMP_TTL_SEC = int(os.getenv("IDEMP_TTL_SEC", "900"))
PRICE_CACHE_TTL_MS = int(os.getenv("PRICE_CACHE_TTL_MS", "250"))

ACCOUNT_TTL_SEC = int(os.getenv("ACCOUNT_TTL_SEC", "2"))
ACCOUNT_ON_BAN_BACKOFF = int(os.getenv("ACCOUNT_ON_BAN_BACKOFF_SEC", "60"))

HEDGE_MODE_OVERRIDE = os.getenv("HEDGE_MODE", "").strip().lower()
HEDGE_MODE_TTL_SEC = int(os.getenv("HEDGE_MODE_TTL_SEC", "30"))
_HEDGE_MODE_CACHE: Dict[str, Any] = {"ts": 0.0, "val": None}

ORDER_ID_PREFIX = os.getenv("ORDER_ID_PREFIX", "").strip()
CANCEL_ONLY_PREFIXED_ORDERS = os.getenv("CANCEL_ONLY_PREFIXED_ORDERS", "0").lower() in ("1", "true", "yes", "on")
CANCEL_PREFIX_OVERRIDE = os.getenv("CANCEL_PREFIX_OVERRIDE", "").strip()

def _now() -> float: return time.time()
def _ms() -> int: return int(time.time() * 1000)

try:
    from utils.ws_fallback import get_price as ws_get_price, is_price_fresh as ws_is_fresh, update_price as ws_update_price
except Exception:
    ws_get_price = None  # type: ignore
    ws_is_fresh = None  # type: ignore
    ws_update_price = None  # type: ignore

_exinfo_cache: Dict[str, Any] = {"ts": 0.0, "data": None}
_account_cache: Dict[str, Any] = {"ts": 0.0, "data": None, "ban_until": 0.0}

_price_cache: Dict[str, Tuple[float, float]] = {}
_index_cache: Dict[str, Tuple[float, float]] = {}

_idem_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_idem_lock = threading.RLock()

_BINANCE_HTTP_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
_client_lock = threading.RLock()
_CLIENT: Optional[Client] = None
_client_ban_until: float = 0.0

def _init_client() -> Optional[Client]:
    global _CLIENT, _client_ban_until
    if not _BINANCE_AVAILABLE:
        logger.warning("python-binance unavailable — client stub active")
        return None
    if not (API_KEY and API_SECRET):
        logger.warning("BINANCE API keys missing — client will remain uninitialized until keys provided")
        return None
    now = _now()
    if _client_ban_until and now < _client_ban_until:
        return None
    try:
        c = Client(API_KEY, API_SECRET, requests_params={"timeout": HTTP_TIMEOUT})
        c.API_URL = _BINANCE_HTTP_BASE
        try:
            try:
                server_time = c.futures_time().get("serverTime")  # type: ignore
            except Exception:
                server_time = c.get_server_time().get("serverTime")
            local_ms = int(time.time() * 1000)
            offset = int(server_time) - local_ms
            setattr(c, "TIME_OFFSET", offset)
            try:
                setattr(c, "timestamp_offset", offset)
            except Exception:
                pass
            logger.info("Binance TIME_OFFSET set to %d ms", offset)
        except Exception as e:
            logger.warning("Time sync failed: %s", e)
        _CLIENT = c
        return _CLIENT
    except BinanceAPIException as e:
        s = str(e)
        code = getattr(e, "code", None)
        status = getattr(e, "status_code", None)
        if "429" in s or "-1003" in s or status == 429 or code in (-1003,):
            backoff = max(ACCOUNT_ON_BAN_BACKOFF, 10)
            _client_ban_until = _now() + backoff
            logger.error("Binance client init rate-limited/banned; deferring %.0fs", backoff)
            return None
        logger.error("Binance client init failed: %s", e)
        return None
    except Exception as e:
        logger.error("Binance client init failed: %s", e)
        return None

def _get_client() -> Optional[Client]:
    global _CLIENT
    with _client_lock:
        if _CLIENT is not None:
            return _CLIENT
        return _init_client()

class _ClientProxy:
    def __getattr__(self, name: str):
        c = _get_client()
        if c is None:
            raise RuntimeError("Binance REST unavailable (library/keys missing or client not ready/banned)")
        return getattr(c, name)

client: Client | _ClientProxy = _ClientProxy()

def get_futures_client():
    return _get_client() or client

@observe_http(name="binance_exinfo")
def futures_exchange_info_safe(force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    ts = _now()
    if not force_refresh and _exinfo_cache["data"] and (ts - _exinfo_cache["ts"] < EXINFO_TTL):
        return _exinfo_cache["data"]
    try:
        data = client.futures_exchange_info()
        _exinfo_cache["data"] = data
        _exinfo_cache["ts"] = ts
        return data
    except Exception as e:
        logger.error("futures_exchange_info failed: %s", e)
        return _exinfo_cache["data"]

@observe_http(name="binance_ping")
def fapi_ping() -> bool:
    try:
        client.futures_ping()
        return True
    except Exception as e:
        logger.warning("Futures ping failed: %s", e)
        return False

def get_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    info = futures_exchange_info_safe() or {}
    su = symbol.upper()
    for s in info.get("symbols", []):
        if (s.get("symbol") or "").upper() == su:
            return s
    return None

def get_symbol_filters(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        si = get_symbol_info(symbol)
        if not si:
            return None
        filters: Dict[str, Any] = {
            "tickSize": None, "minPrice": None, "maxPrice": None,
            "stepSize": None, "minQty": None, "maxQty": None,
            "mMinQty": None, "mMaxQty": None, "minNotional": None,
            "percentPrice": {"up": None, "down": None, "decimals": None},
        }
        for f in si.get("filters", []):
            t = f.get("filterType")
            if t == "PRICE_FILTER":
                filters["tickSize"] = f.get("tickSize"); filters["minPrice"] = f.get("minPrice"); filters["maxPrice"] = f.get("maxPrice")
            elif t == "LOT_SIZE":
                filters["minQty"] = f.get("minQty"); filters["maxQty"] = f.get("maxQty"); filters["stepSize"] = f.get("stepSize")
            elif t in ("MARKET_Lot_SIZE", "MARKET_LOT_SIZE"):
                filters["mMinQty"] = f.get("minQty"); filters["mMaxQty"] = f.get("maxQty")
            elif t in ("MIN_NOTIONAL", "NOTIONAL"):
                filters["minNotional"] = f.get("notional") or f.get("minNotional")
            elif t == "PERCENT_PRICE":
                filters["percentPrice"] = {"up": f.get("multiplierUp"), "down": f.get("multiplierDown"), "decimals": f.get("multiplierDecimal")}
        if not filters["tickSize"]:
            filters["tickSize"] = DEFAULT_PRICE_TICK_STR
        if not filters["stepSize"]:
            filters["stepSize"] = DEFAULT_QTY_STEP_STR
        if not filters["minNotional"]:
            filters["minNotional"] = DEFAULT_MIN_NOTIONAL
        return filters
    except Exception as e:
        logger.error("Failed get_symbol_filters: %s", e)
        return None

def _decs(step: str) -> int:
    if "." not in step: return 0
    frac = step.split(".", 1)[1].rstrip("0")
    return len(frac)

def _quantize_price(symbol: str, price: float) -> str:
    f = get_symbol_filters(symbol) or {}
    tick = float(f.get("tickSize") or DEFAULT_PRICE_TICK_STR)
    if tick <= 0: tick = float(DEFAULT_PRICE_TICK_STR)
    steps = round(price / tick)
    adj = steps * tick
    decs = _decs(str(f.get("tickSize") or DEFAULT_PRICE_TICK_STR))
    return f"{adj:.{decs}f}"

def _quantize_qty(symbol: str, qty: float) -> str:
    f = get_symbol_filters(symbol) or {}
    step = float(f.get("stepSize") or DEFAULT_QTY_STEP_STR)
    if step <= 0: step = float(DEFAULT_QTY_STEP_STR)
    if qty <= 0: return "0"
    steps = math.floor(max(qty, 0.0) / step)
    adj = max(step, steps * step)
    decs = _decs(str(f.get("stepSize") or DEFAULT_QTY_STEP_STR))
    return f"{adj:.{decs}f}"

def _ensure_min_notional_qty(symbol: str, price: float, qty_str: str) -> str:
    try:
        mn = float((get_symbol_filters(symbol) or {}).get("minNotional") or DEFAULT_MIN_NOTIONAL)
    except Exception:
        mn = DEFAULT_MIN_NOTIONAL
    qf = float(qty_str)
    if price * qf >= mn:
        return qty_str
    need = mn / max(price, 1e-12)
    return _quantize_qty(symbol, need)

def _cache_get(cache: Dict[str, Tuple[float, float]], symbol: str) -> Optional[float]:
    ts_ms, val = cache.get(symbol.upper(), (0.0, 0.0))
    if _ms() - ts_ms <= PRICE_CACHE_TTL_MS:
        return val
    return None

def _cache_put(cache: Dict[str, Tuple[float, float]], symbol: str, value: float) -> None:
    cache[symbol.upper()] = (_ms(), float(value))

@observe_http(name="binance_mark_price", include_labels=["symbol"])
def futures_mark_price(symbol: str) -> Optional[float]:
    sym = symbol.upper()
    try:
        cached = _cache_get(_price_cache, sym)
        if cached is not None:
            return cached
        d = client.futures_mark_price(symbol=sym)
        p = float(d.get("markPrice") or 0.0)
        if p > 0:
            _cache_put(_price_cache, sym, p)
        return p if p > 0 else None
    except Exception as e:
        logger.error("Failed mark price for %s: %s", sym, e)
        return None

@observe_http(name="binance_index_price", include_labels=["symbol"])
def futures_index_price(symbol: str) -> Optional[float]:
    sym = symbol.upper()
    try:
        cached = _cache_get(_index_cache, sym)
        if cached is not None:
            return cached
    except Exception:
        pass
    try:
        if hasattr(client, "futures_premium_index"):
            data = client.futures_premium_index(symbol=sym)
            if isinstance(data, list) and data:
                data = data[0]
            p = data.get("indexPrice")
            if p is not None:
                val = float(p)
                _cache_put(_index_cache, sym, val)
                return val
    except Exception:
        pass
    try:
        if hasattr(client, "_request_futures_api"):
            data = client._request_futures_api("get", "premiumIndex", data={"symbol": sym})  # type: ignore
            if isinstance(data, list) and data:
                data = data[0]
            p = data.get("indexPrice")
            if p is not None:
                val = float(p)
                _cache_put(_index_cache, sym, val)
                return val
    except Exception:
        pass
    try:
        import httpx  # type: ignore
        base = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
        url = f"{base}/fapi/v1/premiumIndex"
        with observe_http_ctx(name="binance_http"):
            with httpx.Client(timeout=float(os.getenv("BINANCE_HTTP_TIMEOUT", "10.0"))) as cli:
                r = cli.get(url, params={"symbol": sym})
                r.raise_for_status()
                data = r.json()
                if isinstance(data, list) and data:
                    data = data[0]
                p = data.get("indexPrice")
                if p is not None:
                    val = float(p)
                    _cache_put(_index_cache, sym, val)
                    return val
    except Exception as e:
        logger.error("HTTP premiumIndex failed for %s: %s", sym, e)
    return None

def get_price(symbol: str) -> Optional[float]:
    try:
        if ws_get_price and ws_is_fresh and ws_is_fresh(symbol):
            v = ws_get_price(symbol)
            if v:
                return float(v)
    except Exception:
        pass
    return futures_mark_price(symbol)

@observe_http(name="binance_balance")
def futures_balance() -> List[Dict[str, Any]]:
    try:
        data = client.futures_account()
        return data.get("assets") or data.get("balances") or client.futures_account_balance() or []
    except Exception as e:
        logger.error("Failed to fetch futures_balance: %s", e)
        return []

@observe_http(name="binance_positions", include_labels=["symbol"])
def get_open_positions(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        acc_info = client.futures_account() or {}
        positions = acc_info.get("positions", []) or []
        out = []
        su = symbol.upper() if symbol else None
        for pos in positions:
            amt = float(pos.get("positionAmt", "0") or 0.0)
            if abs(amt) > 1e-12 and (su is None or (str(pos.get("symbol") or "").upper() == su)):
                out.append(pos)
        return out
    except Exception as e:
        logger.error("Failed to get open positions: %s", e)
        return []

def futures_open_positions_safe(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    return get_open_positions(symbol)

def get_single_position(symbol: str) -> Optional[Dict[str, Any]]:
    for p in get_open_positions(symbol):
        return p
    return None

def get_position_info(symbol: str) -> Dict[str, Any]:
    """Alias for get_single_position - used by fills_watcher and trade_manager"""
    return get_single_position(symbol) or {}

@observe_http(name="binance_open_orders", include_labels=["symbol"])
def get_open_orders(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        if symbol:
            return cast(List[Dict[str, Any]], client.futures_get_open_orders(symbol=symbol.upper()) or [])
        return cast(
            List[Dict[str, Any]],
            client.futures_get_open_orders() or []
        )
    except Exception as e:
        logger.error("Failed to get open orders: %s", e)
        return []

# Alias for fills_watcher compatibility
def futures_get_open_orders(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """Alias for get_open_orders - used by fills_watcher and position_manager"""
    return get_open_orders(symbol)

@observe_http(name="binance_all_orders", include_labels=["symbol"])
def get_all_orders(symbol: str, limit: int = 100, **kwargs) -> List[Dict[str, Any]]:
    if not symbol or not symbol.strip():
        return []
    limit = max(1, min(int(limit), 1000))
    try:
        return cast(List[Dict[str, Any]], client.futures_get_all_orders(symbol=symbol.upper(), limit=limit, **kwargs) or [])
    except BinanceAPIException as e:
        logger.error("get_all_orders failed: %s", e)
        return []
    except Exception as e:
        logger.error("get_all_orders error: %s", e)
        return []

@observe_http(name="binance_cancel_order", include_labels=["symbol"])
def futures_cancel_order(symbol: str, order_id: str | int) -> Dict[str, Any]:
    try:
        return client.futures_cancel_order(symbol=symbol.upper(), orderId=int(order_id))
    except Exception as e:
        logger.warning("cancel_order failed %s/%s: %s", symbol, order_id, e)
        return {"ok": False, "error": str(e)}

# ✅ חדש: ביטול כל ההזמנות (לבקשת routes.grid)
@observe_http(name="binance_cancel_all", include_labels=["symbol"])
def futures_cancel_all_orders(symbol: str) -> Dict[str, Any]:
    try:
        res = client.futures_cancel_all_open_orders(symbol=symbol.upper())
        return {"ok": True, "result": res}
    except Exception as e:
        logger.error("futures_cancel_all_orders failed for %s: %s", symbol, e)
        return {"ok": False, "error": str(e)}

# ──────────────────────────────────────────────────────────────────────────────
# תאימות לאחור: place_limit_order / cancel_order
# ──────────────────────────────────────────────────────────────────────────────

def place_limit_order(symbol: str, side: str, quantity: float, price: float, **kwargs) -> Dict[str, Any]:
    params = {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "type": "LIMIT",
        "timeInForce": kwargs.pop("timeInForce", "GTC"),
        "quantity": quantity,
        "price": price,
    }
    params.update(kwargs)
    return futures_create_order(**params)

def cancel_order(symbol: str, order_id: str | int) -> Dict[str, Any]:
    """שם ישן בו משתמשים ראוטים שונים."""
    return futures_cancel_order(symbol, order_id)

def get_price_coalesced(symbol: str) -> Optional[float]:
    v = get_price(symbol)
    if v is not None:
        return float(v)
    return futures_index_price(symbol)

# ──────────────────────────────────────────────────────────────────────────────
# יצירת הזמנות נוחות לשימוש (כולל עטיפות תאימות־שם לראוטים)
# ──────────────────────────────────────────────────────────────────────────────

@observe_http(name="binance_create_order", include_labels=["symbol"])
def futures_create_order(**kwargs) -> Dict[str, Any]:
    sym = str(kwargs.get("symbol") or "").upper()
    if not sym:
        raise ValueError("symbol required")
    typ = str(kwargs.get("type") or "").upper()
    qty = kwargs.get("quantity")
    price = kwargs.get("price")
    stop = kwargs.get("stopPrice")
    activation = kwargs.get("activationPrice")
    if qty is not None:
        kwargs["quantity"] = _quantize_qty(sym, float(qty))
    if price is not None:
        p_str = _quantize_price(sym, float(price))
        # guard
        kwargs["price"] = p_str
    if stop is not None:
        s_str = _quantize_price(sym, float(stop))
        kwargs["stopPrice"] = s_str
    if activation is not None:
        a_str = _quantize_price(sym, float(activation))
        kwargs["activationPrice"] = a_str
    if "workingType" not in kwargs:
        kwargs["workingType"] = WORKING_TYPE
    coid = str(kwargs.get("newClientOrderId") or "")
    if coid:
        if ORDER_ID_PREFIX and not coid.startswith(ORDER_ID_PREFIX):
            coid = f"{ORDER_ID_PREFIX}_{coid}"
        if len(coid) > 36:
            coid = coid[:36]
        kwargs["newClientOrderId"] = coid
    elif ORDER_ID_PREFIX:
        kwargs["newClientOrderId"] = f"{ORDER_ID_PREFIX}_{int(_ms() % 10 ** 9)}"
    
    # ✅ SMART POSITION MODE COMPATIBILITY
    # Adapt order parameters based on detected position mode (HEDGE vs ONE-WAY)
    # This prevents -4061 errors when position mode doesn't match order params
    try:
        from utils.position_mode import adapt_order_for_mode
        side = str(kwargs.get("side", "BUY")).upper()
        kwargs = adapt_order_for_mode(kwargs, side)
    except Exception as e:
        # Don't crash on adaptation failure - just log and proceed
        print(f"[WARN] Position mode adaptation failed: {e}")
    
    # Smart reduceOnly handling for Hedge Mode
    # CRITICAL: In Hedge Mode (positionSide present), Binance NEVER needs reduceOnly
    # The positionSide already indicates if we're closing LONG or SHORT
    close_position = kwargs.get("closePosition", False)
    position_side = kwargs.get("positionSide")
    
    # Rule 1: closePosition=true → remove reduceOnly and other forbidden params
    if typ in {"STOP_MARKET", "TAKE_PROFIT_MARKET"} and close_position:
        for forbidden in ("reduceOnly", "quantity", "price", "timeInForce", "postOnly"):
            kwargs.pop(forbidden, None)
        print(f"[DEBUG futures_create_order] closePosition=true, removed forbidden params")
    
    # Rule 2: In Hedge Mode (positionSide present) → ALWAYS remove reduceOnly
    elif position_side:
        if kwargs.get("reduceOnly"):
            kwargs.pop("reduceOnly", None)
            print(f"[DEBUG futures_create_order] Removed reduceOnly (Hedge Mode, positionSide={position_side})")
    
    print(f"[DEBUG futures_create_order] Final: positionSide={kwargs.get('positionSide')!r}, reduceOnly={kwargs.get('reduceOnly')!r}")
    last: Optional[Exception] = None
    for attempt in range(1, max(1, BINANCE_MAX_RETRIES) + 1):
        try:
            res = client.futures_create_order(recvWindow=RECV_WINDOW, **kwargs)
            return res or {}
        except BinanceAPIException as e:
            last = e
            time.sleep(min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * attempt) / 1000.0)
            continue
        except Exception as e:
            last = e
            time.sleep(min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * attempt) / 1000.0)
            continue
    raise RuntimeError(f"create_order_failed:{sym}:{typ}:{str(last) if last else 'unknown_error'}")

def place_stop_market(
    symbol: str,
    side: str,
    stop_price: float,
    quantity: float,
    *,
    reduce_only: bool = True,
    positionSide: Optional[str] = None,
    workingType: Optional[str] = None
) -> Dict[str, Any]:
    """STOP_MARKET SL/BE/Lock."""
    args: Dict[str, Any] = {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "type": "STOP_MARKET",
        "stopPrice": _quantize_price(symbol, float(stop_price)),
        "quantity": _quantize_qty(symbol, float(quantity)),
        "reduceOnly": bool(reduce_only),
        "timeInForce": "GTC",
        "workingType": (workingType or WORKING_TYPE),
    }
    if positionSide and HEDGE_MODE_OVERRIDE not in ("0", "false", "no", "off", "oneway"):
        args["positionSide"] = positionSide.upper()
    return futures_create_order(**args)

# ✔ עטיפת תאימות לשם שהראוטים מחפשים
def place_stop_market_order(
    symbol: str,
    side: str,
    stop_price: float,
    quantity: float,
    *,
    reduce_only: bool = True,
    position_side: Optional[str] = None,
) -> Dict[str, Any]:
    return place_stop_market(
        symbol=symbol,
        side=side,
        stop_price=stop_price,
        quantity=quantity,
        reduce_only=reduce_only,
        positionSide=position_side,
    )

def place_take_profit_market(
    symbol: str,
    side: str,
    stop_price: float,
    quantity: float,
    *,
    reduce_only: bool = True,
    position_side: Optional[str] = None,
    workingType: Optional[str] = None
) -> Dict[str, Any]:
    """TAKE_PROFIT_MARKET – ל־TP."""
    args: Dict[str, Any] = {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "type": "TAKE_PROFIT_MARKET",
        "stopPrice": _quantize_price(symbol, float(stop_price)),
        "quantity": _quantize_qty(symbol, float(quantity)),
        "reduceOnly": bool(reduce_only),
        "timeInForce": "GTC",
        "workingType": (workingType or WORKING_TYPE),
    }
    if position_side and HEDGE_MODE_OVERRIDE not in ("0", "false", "no", "off", "oneway"):
        args["positionSide"] = position_side.upper()
    return futures_create_order(**args)

def set_breakeven_stop(
    symbol: str,
    entry_price: float,
    side_opened: str,
    *,
    offset_bps: float = 8.0,
    qty_hint: Optional[float] = None,
    positionSide: Optional[str] = None
) -> Dict[str, Any]:
    try:
        q = qty_hint
        if not q or q <= 0:
            for p in get_open_positions(symbol):
                amt = float(p.get("positionAmt") or 0.0)
                if abs(amt) > 0:
                    q = abs(amt)
                    break
        if not q or q <= 0:
            raise RuntimeError("qty_missing")
        side_u = side_opened.upper()
        close_side = "SELL" if side_u in ("BUY", "LONG") else "BUY"
        be = float(entry_price) * (1.0 + (offset_bps / 10000.0 if close_side == "SELL" else -offset_bps / 10000.0))
        try:
            for o in get_open_orders(symbol):
                typ = (o.get("type") or "").upper()
                st = (o.get("status") or "").upper()
                if "STOP" in typ and st in ("NEW", "PARTIALLY_FILLED"):
                    oid = o.get("orderId")
                    if oid is not None:
                        futures_cancel_order(symbol, oid)
        except Exception:
            pass
        return place_stop_market(symbol, close_side, be, float(q), positionSide=positionSide)
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_klines_df(symbol: str, interval: str = "5m", limit: int = 120):
    try:
        import pandas as pd  # type: ignore
        arr = client.futures_klines(symbol=symbol.upper(), interval=interval, limit=min(max(limit, 50), 1000)) or []
        if not arr:
            return None
        cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
        df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df
    except Exception:
        return None

def close_all_positions() -> Dict[str, Any]:
    closed = []
    try:
        for p in get_open_positions():
            sym = (p.get("symbol") or "").upper()
            amt = float(p.get("positionAmt") or 0.0)
            if not sym or abs(amt) <= 0:
                continue
            side_opened = "BUY" if amt > 0 else "SELL"
            close_side = "SELL" if side_opened == "BUY" else "BUY"
            qty_str = _quantize_qty(sym, abs(amt))
            args = {"symbol": sym, "side": close_side, "type": "MARKET", "reduceOnly": True, "quantity": qty_str}
            try:
                closed.append(futures_create_order(**args))
            except Exception as e:
                closed.append({"ok": False, "error": str(e), "symbol": sym})
        return {"ok": True, "closed": closed}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def apply_price_tick_side(price: float, symbol: str, side: str) -> tuple[str, float]:
    p_str = _quantize_price(symbol, float(price))
    p = float(p_str)
    try:
        f = get_symbol_filters(symbol) or {}
        tick = float(f.get("tickSize") or DEFAULT_PRICE_TICK_STR)
        if side.upper() == "SELL":
            p = max(tick, p - tick)
            p_str = _quantize_price(symbol, p)
    except Exception:
        pass
    return p_str, float(p_str)

# ──────────────────────────────────────────────────────────────────────────────
# מינוף FUTURES — עטיפה בטוחה שלא מפילה את המערכת
# ──────────────────────────────────────────────────────────────────────────────
def set_leverage(symbol: str, leverage: int, *, client: Optional[Client] = None) -> bool:
    """
    מעטפת בטוחה להגדרת מינוף על Binance Futures.
    מחזירה True בהצלחה, False בכישלון — לא מפילה את המערכת.
    """
    try:
        sym = (symbol or "").upper().strip()
        lev = int(leverage or 0)
        if not sym or lev <= 0:
            return False

        # קבלת client קיים או lazy-init מהקובץ
        cli = client or _get_client()
        if cli is None:
            logger.warning("set_leverage: client unavailable (keys/library/init).")
            return False

        # אופציונלי: שליטה במצב פוזיציה לפי ENV (אם קיים)
        mode = (HEDGE_MODE_OVERRIDE or "").strip().lower()
        try:
            if mode in ("hedge", "dual", "dual_side", "dualposition", "dual_side_position"):
                with suppress(Exception):
                    cli.futures_change_position_mode(dualSidePosition="true")  # type: ignore[attr-defined]
            elif mode in ("oneway", "one_way", "single", "single_side", "oneside", "0", "off", "false", "no"):
                with suppress(Exception):
                    cli.futures_change_position_mode(dualSidePosition="false")  # type: ignore[attr-defined]
        except Exception:
            # לא קריטי
            pass

        # שינוי מינוף
        cli.futures_change_leverage(symbol=sym, leverage=lev)  # type: ignore[attr-defined]
        logger.info("set_leverage: %s -> x%d", sym, lev)
        return True
    except Exception as e:
        logger.warning("set_leverage failed (%s): %s", symbol, e)
        return False

__all__ = [
    "client",
    "get_futures_client",
    "futures_exchange_info_safe",
    "fapi_ping",
    "get_symbol_info",
    "get_symbol_filters",
    "futures_mark_price",
    "futures_index_price",
    "get_price",
    "get_price_coalesced",
    "futures_balance",
    "get_open_positions",
    "futures_open_positions_safe",
    "get_single_position",
    "get_open_orders",
    "get_all_orders",
    "futures_cancel_order",
    "futures_cancel_all_orders",   # ✔ עבור routes.grid
    "futures_create_order",
    "place_limit_order",
    "cancel_order",
    "place_stop_market",
    "place_stop_market_order",     # ✔ תאימות שם לראוט
    "place_take_profit_market",    # ✔ חדש
    "set_breakeven_stop",
    "get_klines_df",
    "close_all_positions",
    "apply_price_tick_side",
    "set_leverage",                # ← נוספה ל־__all__
]









































































































































































































