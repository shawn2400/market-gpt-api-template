# utils/binance_client.py
from __future__ import annotations
import os, time, math, logging, threading
from typing import Any, Dict, List, Optional, Iterable, Tuple

from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger("algogpt.binance")

# ===== ENV =====
API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
if not API_KEY or not API_SECRET:
    logger.error("[binance_client] Missing API keys")
    raise RuntimeError("Missing Binance API keys")

HTTP_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "10.0"))
WORKING_TYPE = os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE").upper()
RECV_WINDOW = int(os.getenv("BINANCE_RECV_WINDOW", "15000"))

EXINFO_TTL = int(os.getenv("EXCHANGE_INFO_TTL_SEC", "900"))
ORD_BUCKET_WINDOW = int(os.getenv("ORDERS_BUCKET_WINDOW_SEC", "10"))
ORD_QPS_BUCKET = int(os.getenv("ORDERS_QPS_BUCKET", "4"))
BACKOFF_BASE_MS = int(os.getenv("ORDER_BACKOFF_BASE_MS", "120"))
BACKOFF_MAX_MS  = int(os.getenv("ORDER_BACKOFF_MAX_MS",  "1600"))
BINANCE_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "6"))

DEFAULT_QTY_STEP_STR = os.getenv("DEFAULT_QTY_STEP", "0.001")
DEFAULT_PRICE_TICK_STR = os.getenv("DEFAULT_PRICE_TICK", "0.01")
DEFAULT_MIN_NOTIONAL = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

# Percent-Guard
PERCENT_GUARD_ENABLE = os.getenv("PERCENT_GUARD_ENABLE", "1") in ("1","true","yes","on")
PERCENT_GUARD_BPS = int(os.getenv("PERCENT_GUARD_BPS", "50"))  # ±0.50% ברירת מחדל

# Idempotency
IDEMP_TTL_SEC = int(os.getenv("IDEMP_TTL_SEC", "900"))

# Price coalescing
PRICE_CACHE_TTL_MS = int(os.getenv("PRICE_CACHE_TTL_MS", "250"))

# ===== Account/Positions cache =====
ACCOUNT_TTL_SEC = int(os.getenv("ACCOUNT_TTL_SEC", "2"))
ACCOUNT_ON_BAN_BACKOFF = int(os.getenv("ACCOUNT_ON_BAN_BACKOFF_SEC", "10"))

# ===== Hedge/One-Way detection (runtime + override) =====
HEDGE_MODE_OVERRIDE = os.getenv("HEDGE_MODE", "").strip().lower()
_HEDGE_MODE_CACHE: Optional[bool] = None

def _is_hedge_mode_runtime() -> bool:
    """True אם החשבון במצב Hedge; אחרת False (One-Way). כיבוד override דרך HEDGE_MODE."""
    global _HEDGE_MODE_CACHE
    if HEDGE_MODE_OVERRIDE in ("1","true","yes","on","hedge"):  # כפייה ל-Hedge
        return True
    if HEDGE_MODE_OVERRIDE in ("0","false","no","off","oneway"):  # כפייה ל-One-Way
        return False
    try:
        acc = _get_account_cached() or {}
        # לפי מבנה Binance: dualSidePosition=True → Hedge
        dual = bool(acc.get("dualSidePosition"))
        _HEDGE_MODE_CACHE = dual
        return dual
    except Exception:
        # בהיעדר מידע – ברירת מחדל שמרנית: One-Way
        return False

def _effective_position_side_from_kwargs(kwargs: Dict[str, Any]) -> str:
    """
    מחזיר LONG/SHORT אם הועבר positionSide בחשבון Hedge. ב-One-Way או אם לא חוקי – מחזיר 'BOTH'.
    בנוסף, אם One-Way ונשלח positionSide – נסיר אותו מה-kwargs (סניטציה).
    """
    ps = str(kwargs.get("positionSide") or "").upper().strip()
    if not _is_hedge_mode_runtime():
        # One-Way → לא שולחים positionSide בכלל
        kwargs.pop("positionSide", None)
        return "BOTH"
    if ps in ("LONG","SHORT"):
        return ps
    kwargs.pop("positionSide", None)
    return "BOTH"

# ===== Ladder ENV =====
LADDER_TP_ENABLE = os.getenv("LADDER_TP_ENABLE", "1") in ("1","true","yes","on")
LADDER_TP_KIND = os.getenv("LADDER_TP_KIND", "TAKE_PROFIT_MARKET").upper()
LADDER_TP_DEFAULT_PCTS = os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5")
LADDER_TP_DEFAULT_SPLITS = os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25")
LADDER_TP_MAX_LEVELS = int(os.getenv("LADDER_TP_MAX_LEVELS", "5"))

LADDER_SL_ENABLE = os.getenv("LADDER_SL_ENABLE", "0") in ("1","true","yes","on")
LADDER_SL_DEFAULT_PCTS = os.getenv("LADDER_SL_DEFAULT_PCTS", "")
LADDER_SL_MAX_LEVELS = int(os.getenv("LADDER_SL_MAX_LEVELS", "3"))

TP_LADDER_COOLDOWN_SEC = int(os.getenv("TP_LADDER_COOLDOWN_SEC", "60"))
_tp_ladder_last_at: Dict[str, float] = {}

CANCEL_ONLY_PREFIXED_ORDERS = os.getenv("CANCEL_ONLY_PREFIXED_ORDERS", "0") in ("1","true","yes","on")
CANCEL_PREFIX_OVERRIDE = os.getenv("CANCEL_PREFIX_OVERRIDE", "").strip()

# ===== ClientOrderId ENV =====
ORDER_ID_PREFIX = os.getenv("ORDER_ID_PREFIX", "").strip()
ORDER_ID_SUFFIX = os.getenv("ORDER_ID_SUFFIX", "").strip()
ORDER_ID_INCLUDE_TS = os.getenv("ORDER_ID_INCLUDE_TS", "1").lower() in ("1","true","yes","on")
ORDER_ID_MAXLEN = int(os.getenv("ORDER_ID_MAXLEN", "36"))

def _sanitize_coid(s: str) -> str:
    out = []
    for ch in s:
        out.append(ch if (ch.isalnum() or ch == "_") else "_")
    return "".join(out)[:ORDER_ID_MAXLEN]

def _coid(kind: str, symbol: str, level: int | None = None) -> str:
    k = kind.upper()
    if level is not None and k in ("TP", "SL"):
        k = f"{k}{level}"
    parts = []
    if ORDER_ID_PREFIX:
        parts.append(ORDER_ID_PREFIX)
    parts.append(k); parts.append(symbol.upper())
    if level is not None and kind.upper() not in ("TP", "SL"):
        parts.append(str(level))
    if ORDER_ID_INCLUDE_TS:
        parts.append(str(int(time.time() * 1000)))
    if ORDER_ID_SUFFIX:
        parts.append(ORDER_ID_SUFFIX)
    return _sanitize_coid("_".join(parts))

def _kind_from_kwargs(kwargs: dict) -> str:
    t = str(kwargs.get("type", "")).upper()
    if "TAKE_PROFIT" in t: return "TP"
    if "STOP" in t: return "SL"
    if t == "MARKET": return "MKT"
    if t == "LIMIT":  return "LMT"
    return "ORD"

# ===== Init Futures client (+ timeout) =====
_client_lock = threading.RLock()
client = Client(API_KEY, API_SECRET, requests_params={"timeout": HTTP_TIMEOUT})
client.API_URL = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

# Time sync
try:
    try:
        server_time = client.futures_time().get("serverTime")  # type: ignore
    except Exception:
        server_time = client.get_server_time().get("serverTime")
    local_ms = int(time.time() * 1000)
    offset = int(server_time) - local_ms
    setattr(client, "TIME_OFFSET", offset)
    try:
        setattr(client, "timestamp_offset", offset)
    except Exception:
        pass
    logger.info("Binance TIME_OFFSET set to %d ms", offset)
except Exception as e:
    logger.warning("Time sync failed: %s", e)

# Optional WS fallback
try:
    from utils.ws_fallback import get_price as ws_get_price, is_price_fresh as ws_is_fresh, update_price as ws_update_price
except Exception:
    ws_get_price = None  # type: ignore
    ws_is_fresh = None   # type: ignore
    ws_update_price = None  # type: ignore

# ===== Caches =====
_exinfo_cache: Dict[str, Any] = {"ts": 0.0, "data": None}
_account_cache: Dict[str, Any] = {"ts": 0.0, "data": None, "ban_until": 0.0}

# price cache (coalescing)
_price_cache: Dict[str, Tuple[float, float]] = {}  # symbol -> (ts_ms, mark)
_index_cache: Dict[str, Tuple[float, float]] = {}  # symbol -> (ts_ms, index)

# idempotency cache
_idem_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_idem_lock = threading.RLock()

# ===== Helpers =====
def _now() -> float:
    return time.time()

def _ms() -> int:
    return int(time.time() * 1000)

def _get_exchange_info_cached(force_refresh: bool=False) -> Optional[Dict[str, Any]]:
    ts = _now()
    if not force_refresh and _exinfo_cache["data"] and (ts - _exinfo_cache["ts"] < EXINFO_TTL):
        return _exinfo_cache["data"]
    try:
        data = client.futures_exchange_info()
        _exinfo_cache["data"] = data; _exinfo_cache["ts"] = ts
        return data
    except Exception as e:
        logger.error("futures_exchange_info failed: %s", e)
        return _exinfo_cache["data"]

def fapi_ping() -> bool:
    try:
        client.futures_ping()
        return True
    except Exception as e:
        logger.warning("Futures ping failed: %s", e)
        return False

def futures_exchange_info_safe(force_refresh: bool=False) -> Optional[Dict[str, Any]]:
    return _get_exchange_info_cached(force_refresh=force_refresh)

# ===== Account & Positions =====
def _get_account_cached() -> Optional[Dict[str, Any]]:
    now = _now()
    if _account_cache["ban_until"] and now < _account_cache["ban_until"]:
        return _account_cache["data"]
    if _account_cache["data"] and (now - _account_cache["ts"] <= ACCOUNT_TTL_SEC):
        return _account_cache["data"]
    try:
        data = client.futures_account()
        _account_cache.update({"data": data, "ts": now, "ban_until": 0.0})
        return data
    except BinanceAPIException as e:
        s = str(e)
        code = getattr(e, "code", None)
        status = getattr(e, "status_code", None)
        if "429" in s or "-1003" in s or status == 429 or code in (-1003,):
            _account_cache["ban_until"] = now + ACCOUNT_ON_BAN_BACKOFF
            logger.error("futures_account banned/rate limited; backing off %ss", ACCOUNT_ON_BAN_BACKOFF)
            return _account_cache["data"]
        logger.error("futures_account error: %s", e)
        return _account_cache["data"]
    except Exception as e:
        logger.error("futures_account failed: %s", e)
        return _account_cache["data"]

def futures_balance() -> List[Dict[str, Any]]:
    try:
        data = _get_account_cached() or {}
        return data.get("assets") or data.get("balances") or client.futures_account_balance() or []
    except Exception as e:
        logger.error("Failed to fetch futures_balance: %s", e)
        return []

def get_open_positions(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        acc_info = _get_account_cached() or {}
        positions = acc_info.get("positions", []) or []
        out = []
        su = symbol.upper() if symbol else None
        for pos in positions:
            amt = float(pos.get("positionAmt", "0") or 0.0)
            if abs(amt) > 1e-12 and (su is None or (str(pos.get("symbol") or "").upper() == su)):
                out.append(pos)
        return out
    except Exception as e:
        logger.error("Failed to get open positions: %s", e); return []

def futures_open_positions_safe(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    return get_open_positions(symbol)

def get_single_position(symbol: str) -> Optional[Dict[str, Any]]:
    for p in get_open_positions(symbol):
        return p
    return None

# ===== Filters & Rounding =====
def get_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    info = futures_exchange_info_safe()
    if not info: return None
    su = symbol.upper()
    for s in info.get("symbols", []):
        if (s.get("symbol") or "").upper() == su:
            return s
    return None

def get_symbol_filters(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        si = get_symbol_info(symbol)
        if not si: return None
        filters: Dict[str, Any] = {
            "tickSize": None, "minPrice": None, "maxPrice": None,
            "stepSize": None, "minQty": None, "maxQty": None,
            "mMinQty": None, "mMaxQty": None,
            "minNotional": None,
            "percentPrice": {"up": None, "down": None, "decimals": None},
        }
        for f in si.get("filters", []):
            t = f.get("filterType")
            if t == "PRICE_FILTER":
                filters["tickSize"] = f.get("tickSize")
                filters["minPrice"] = f.get("minPrice")
                filters["maxPrice"] = f.get("maxPrice")
            elif t == "LOT_SIZE":
                filters["minQty"] = f.get("minQty")
                filters["maxQty"] = f.get("maxQty")
                filters["stepSize"] = f.get("stepSize")
            elif t == "MARKET_Lot_SIZE" or t == "MARKET_LOT_SIZE":
                filters["mMinQty"] = f.get("minQty")
                filters["mMaxQty"] = f.get("maxQty")
            elif t in ("MIN_NOTIONAL", "NOTIONAL"):
                filters["minNotional"] = f.get("notional") or f.get("minNotional")
            elif t == "PERCENT_PRICE":
                filters["percentPrice"] = {
                    "up": f.get("multiplierUp"),
                    "down": f.get("multiplierDown"),
                    "decimals": f.get("multiplierDecimal"),
                }
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

def _decimals_from_step(step_str: str) -> int:
    if "." not in step_str: return 0
    frac = step_str.split(".")[1]
    while frac and frac.endswith("0"): frac = frac[:-1]
    return len(frac)

def _quantize_price(symbol: str, price: float) -> str:
    f = get_symbol_filters(symbol) or {}
    tick = float(f.get("tickSize") or DEFAULT_PRICE_TICK_STR)
    if tick <= 0: tick = float(DEFAULT_PRICE_TICK_STR)
    steps = round(price / tick)
    adj = steps * tick
    decs = _decimals_from_step(str(f.get("tickSize") or DEFAULT_PRICE_TICK_STR))
    return f"{adj:.{decs}f}"

def _quantize_qty(symbol: str, qty: float) -> str:
    f = get_symbol_filters(symbol) or {}
    step = float(f.get("stepSize") or DEFAULT_QTY_STEP_STR)
    if step <= 0: step = float(DEFAULT_QTY_STEP_STR)
    steps = math.floor(qty / step)
    adj = max(step, steps * step)
    decs = _decimals_from_step(str(f.get("stepSize") or DEFAULT_QTY_STEP_STR))
    return f"{adj:.{decs}f}"

def _ensure_min_notional(symbol: str, price: float, qty: float) -> float:
    f = get_symbol_filters(symbol) or {}
    try:
        min_notional = float(f.get("minNotional") or DEFAULT_MIN_NOTIONAL)
    except Exception:
        min_notional = DEFAULT_MIN_NOTIONAL
    notional = price * qty
    if notional >= min_notional: return qty
    need = min_notional / max(price, 1e-12)
    return max(need, qty)

def _ensure_min_notional_qty(symbol: str, price: float, qty_str: str) -> str:
    qf = float(qty_str)
    need = _ensure_min_notional(symbol, price, qf)
    if need <= qf + 1e-12: return qty_str
    return _quantize_qty(symbol, need)

# ===== Rate limiting buckets =====
_bucket_reset_at = 0.0; _bucket_used = 0
_dyn_qps = max(1, ORD_QPS_BUCKET)
_dyn_backoff_base = max(60, BACKOFF_BASE_MS)
_last_rl_hit = 0.0; _rl_window = 30.0; _rl_hits = 0

def _rate_allow() -> bool:
    global _bucket_reset_at, _bucket_used, _dyn_qps, _last_rl_hit, _rl_hits
    now = _now()
    if _last_rl_hit and (now - _last_rl_hit) > _rl_window and _rl_hits == 0:
        _dyn_qps = min(ORD_QPS_BUCKET, _dyn_qps + 1); _last_rl_hit = 0.0
    if now >= _bucket_reset_at:
        _bucket_reset_at = now + ORD_BUCKET_WINDOW; _bucket_used = 0
        if _rl_hits > 0: _rl_hits = max(0, _rl_hits - 1)
    if _bucket_used < _dyn_qps:
        _bucket_used += 1; return True
    return False

def _note_rate_limit_hit() -> None:
    global _dyn_qps, _dyn_backoff_base, _last_rl_hit, _rl_hits
    _rl_hits += 1; _last_rl_hit = _now()
    _dyn_qps = max(1, _dyn_qps - 1)
    _dyn_backoff_base = min(BACKOFF_MAX_MS, max(_dyn_backoff_base, int(_dyn_backoff_base * 1.5)))

def _backoff_sleep(attempt: int) -> None:
    delay_ms = min(BACKOFF_MAX_MS, _dyn_backoff_base * (2 ** max(0, attempt - 1)))
    time.sleep(delay_ms / 1000.0)

# ===== Mark / Index price with coalescing =====
def _cache_get(cache: Dict[str, Tuple[float, float]], symbol: str) -> Optional[float]:
    ts_ms, val = cache.get(symbol.upper(), (0.0, 0.0))
    if _ms() - ts_ms <= PRICE_CACHE_TTL_MS:
        return val
    return None

def _cache_put(cache: Dict[str, Tuple[float, float]], symbol: str, value: float) -> None:
    cache[symbol.upper()] = (_ms(), float(value))

def futures_mark_price(symbol: str) -> Optional[float]:
    sym = symbol.upper()
    try:
        cached = _cache_get(_price_cache, sym)
        if cached is not None: return cached
        d = client.futures_mark_price(symbol=sym)
        p = float(d.get("markPrice") or 0.0)
        if p > 0: _cache_put(_price_cache, sym, p)
        return p if p > 0 else None
    except Exception as e:
        logger.error("Failed mark price for %s: %s", sym, e)
        return None

def futures_index_price(symbol: str) -> Optional[float]:
    """
    Index price (premiumIndex). עם coalescing קל.
    """
    sym = symbol.upper()
    try:
        cached = _cache_get(_index_cache, sym)
        if cached is not None: return cached
    except Exception:
        pass

    # 1) מתודה רשמית בספרייה
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
    except Exception as e:
        logger.debug("futures_premium_index method failed: %s", e)
    # 2) API פנימי בספרייה
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
    except Exception as e:
        logger.debug("_request_futures_api premiumIndex failed: %s", e)
    # 3) HTTP ישיר
    try:
        import httpx  # type: ignore
        base = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
        url = f"{base}/fapi/v1/premiumIndex"
        with httpx.Client(timeout=float(os.getenv('BINANCE_HTTP_TIMEOUT', '10.0'))) as cli:
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
# ===== Open orders / history =====
def get_open_orders(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        if symbol: return client.futures_get_open_orders(symbol=symbol.upper()) or []
        return client.futures_get_open_orders() or []
    except Exception as e:
        logger.error("Failed to get open orders: %s", e); return []

def get_all_orders(symbol: str, limit: int = 100, **kwargs) -> List[Dict[str, Any]]:
    if not symbol or not symbol.strip():
        return []
    limit = max(1, min(int(limit), 1000))
    try:
        return client.futures_get_all_orders(symbol=symbol.upper(), limit=limit, **kwargs) or []
    except BinanceAPIException as e:
        logger.error("get_all_orders failed: %s", e); return []
    except Exception as e:
        logger.error("get_all_orders error: %s", e); return []
# ===== Price guard =====
def _percent_guard_ok(symbol: str, price: float) -> bool:
    if not PERCENT_GUARD_ENABLE: 
        return True
    mark = futures_mark_price(symbol)
    if not mark or mark <= 0:
        return True
    f = get_symbol_filters(symbol) or {}
    pp = (f.get("percentPrice") or {}) if f else {}
    try:
        up = float(pp.get("up")) if pp.get("up") is not None else None
        down = float(pp.get("down")) if pp.get("down") is not None else None
    except Exception:
        up = down = None
    if up and down and up > 0 and down > 0:
        lo = mark * float(down)
        hi = mark * float(up)
        return (price >= lo) and (price <= hi)
    bps = max(1, int(PERCENT_GUARD_BPS))
    dev_bps = abs(price - mark) / mark * 10000.0
    return dev_bps <= bps

# ===== Orders / Positions / Helpers =====
def _order_has_prefix(o: Dict[str, Any], prefix: str) -> bool:
    if not prefix:
        return True
    coid = str(o.get("clientOrderId") or o.get("origClientOrderId") or "")
    return coid.startswith(prefix)

def _cancel_closing_orders(symbol: str, types: Iterable[str]) -> int:
    open_orders = get_open_orders(symbol); count = 0
    tset = set(t.upper() for t in types)
    prefix = (CANCEL_PREFIX_OVERRIDE or ORDER_ID_PREFIX or "").strip()
    only_pref = CANCEL_ONLY_PREFIXED_ORDERS

    if only_pref and not prefix:
        logger.warning("CANCEL_ONLY_PREFIXED_ORDERS=1 אך לא הוגדר ORDER_ID_PREFIX/CANCEL_PREFIX_OVERRIDE; לא מבטל הזמנות.")
        return 0

    for o in open_orders:
        otype = (o.get("type") or o.get("origType") or "").upper()
        if otype in tset:
            if only_pref and not _order_has_prefix(o, prefix):
                continue
            oid = o.get("orderId")
            if oid is not None:
                try:
                    client.futures_cancel_order(symbol=symbol.upper(), orderId=oid); count += 1
                except Exception as e:
                    logger.warning("Cancel order failed %s/%s: %s", symbol, oid, e)
    return count

def futures_cancel_all_orders(symbol: str) -> Dict[str, Any]:
    try:
        return client.futures_cancel_all_open_orders(symbol=symbol.upper())
    except Exception as e:
        logger.error("Failed to cancel orders for %s: %s", symbol, e)
        return {"ok": False, "error": str(e)}

def futures_cancel_order(symbol: str, orderId: int | str) -> Dict[str, Any]:
    try:
        return client.futures_cancel_order(symbol=symbol.upper(), orderId=orderId)
    except Exception as e:
        logger.error("Failed to cancel order %s/%s: %s", symbol, orderId, e)
        return {"ok": False, "error": str(e)}

def _position_side_from_amt(amt: float) -> str:
    return "LONG" if amt > 0 else "SHORT"

def _order_side_for_close(pos_side: str) -> str:
    ps = (pos_side or "").upper()
    if ps == "LONG":  return "SELL"
    if ps == "SHORT": return "BUY"
    return "SELL"

# ===== Idempotency =====
_idem_cache: Dict[str, Tuple[float, Dict[str, Any]]]  # (הכרזה כבר בחלק 1)
def _idem_get(coid: str) -> Optional[Dict[str, Any]]:
    with _idem_lock:
        ts_res = _idem_cache.get(coid)
        if not ts_res:
            return None
        ts, res = ts_res
        if (_now() - ts) <= IDEMP_TTL_SEC:
            return res
        try:
            del _idem_cache[coid]
        except Exception:
            pass
        return None

def _idem_put(coid: str, res: Dict[str, Any]) -> None:
    with _idem_lock:
        _idem_cache[coid] = (_now(), res)
        if len(_idem_cache) > 2048:
            dead = [k for k,(t,_) in _idem_cache.items() if (_now() - t) > IDEMP_TTL_SEC]
            for k in dead[:512]:
                _idem_cache.pop(k, None)

# ===== Create/Modify Orders =====
def _safe_create_order(**kwargs) -> Dict[str, Any]:
    kwargs.setdefault("workingType", WORKING_TYPE)
    kwargs.setdefault("recvWindow", RECV_WINDOW)

    # כבדוק Hedge/One-Way וסניטציית positionSide
    eff_ps = _effective_position_side_from_kwargs(kwargs)  # עשוי להסיר positionSide ב-One-Way

    if not str(kwargs.get("newClientOrderId", "")).strip():
        sym = str(kwargs.get("symbol", "UNK")).upper()
        kind = _kind_from_kwargs(kwargs)
        kwargs["newClientOrderId"] = _coid(kind, sym)

    # Percent-guard
    try:
        sym = str(kwargs.get("symbol", "UNK")).upper()
        if "price" in kwargs and kwargs["price"] is not None:
            price_val = float(kwargs["price"])
            if not _percent_guard_ok(sym, price_val):
                return {"ok": False, "error": f"percent_guard price out-of-bounds for {sym}"}
        if "stopPrice" in kwargs and kwargs["stopPrice"] is not None:
            sprice_val = float(kwargs["stopPrice"])
            if not _percent_guard_ok(sym, sprice_val):
                return {"ok": False, "error": f"percent_guard stopPrice out-of-bounds for {sym}"}
    except Exception as _e:
        logger.debug("percent-guard skipped: %s", _e)

    coid = str(kwargs.get("newClientOrderId"))
    if coid:
        idem_hit = _idem_get(coid)
        if idem_hit is not None:
            return idem_hit

    # ===== Retry loop + טיפול מיוחד ב- -1106 (reduceOnly) =====
    def _maybe_retry_without_reduceonly(err: Exception) -> Optional[Dict[str, Any]]:
        msg = str(err).lower()
        if "reduceonly" in msg and "not required" in msg and "reduceonly" in (k.lower() for k in kwargs.keys()):
            k2 = dict(kwargs)
            k2.pop("reduceOnly", None)
            try:
                r2 = client.futures_create_order(**k2)
                if coid: _idem_put(coid, r2 if isinstance(r2, dict) else {"ok": True, "res": r2})
                return r2
            except Exception as e2:
                return {"ok": False, "error": str(e2)}
        return None

    for attempt in range(1, BINANCE_MAX_RETRIES + 1):
        if not _rate_allow():
            _backoff_sleep(attempt); continue
        try:
            res = client.futures_create_order(**kwargs)
            if coid:
                _idem_put(coid, res if isinstance(res, dict) else {"ok": True, "res": res})
            return res
        except BinanceAPIException as e:
            s = str(e); code = getattr(e, "code", None); status = getattr(e, "status_code", None)
            # טיפול רייטלימיט
            if "429" in s or "-1003" in s or status == 429 or code in (-1003,):
                logger.warning("Rate-limited, attempt=%s; qps=%s base=%sms", attempt, _dyn_qps, _dyn_backoff_base)
                _note_rate_limit_hit(); _backoff_sleep(attempt); continue
            # נסה ללא reduceOnly אם רלוונטי
            retry = _maybe_retry_without_reduceonly(e)
            if retry is not None:
                return retry
            logger.error("BinanceAPIException: %s", e)
            err = {"ok": False, "error": str(e)}
            if coid: _idem_put(coid, err)
            return err
        except Exception as e:
            # נסה ללא reduceOnly אם זה המקרה
            retry = _maybe_retry_without_reduceonly(e)
            if retry is not None:
                return retry
            logger.error("futures_create_order failed: %s", e)
            _backoff_sleep(attempt)
            if attempt == BINANCE_MAX_RETRIES:
                err = {"ok": False, "error": str(e)}
                if coid: _idem_put(coid, err)
                return err
    err = {"ok": False, "error": "max_retries_exceeded"}
    if coid: _idem_put(coid, err)
    return err

def futures_create_order(**kwargs) -> Dict[str, Any]:
    """
    עטיפה בטוחה ליצירת הזמנה — עם Idempotency, Percent-Guard, Backoff, WorkingType/recvWindow.
    כולל סניטציה לפי סוג הזמנה, וניקוי reduceOnly אם אינו נדרש ב-One-Way.
    """
    sym = str(kwargs.get("symbol", "UNK")).upper()

    # Quantize
    if "price" in kwargs and kwargs["price"] is not None:
        kwargs["price"] = _quantize_price(sym, float(kwargs["price"]))
    if "stopPrice" in kwargs and kwargs["stopPrice"] is not None:
        kwargs["stopPrice"] = _quantize_price(sym, float(kwargs["stopPrice"]))
    if "quantity" in kwargs and kwargs["quantity"] is not None:
        qty_q = _quantize_qty(sym, float(kwargs["quantity"]))
        ref_price = None
        if kwargs.get("price") is not None:
            ref_price = float(kwargs["price"])
        else:
            try:
                ref_price = futures_mark_price(sym) or futures_index_price(sym)
            except Exception:
                ref_price = None
        if ref_price:
            qty_q = _ensure_min_notional_qty(sym, float(ref_price), qty_q)
        kwargs["quantity"] = qty_q

    # סוג הזמנה → סניטציה
    typ = str(kwargs.get("type") or "").upper()
    if "MARKET" in typ and "timeInForce" in kwargs:
        kwargs.pop("timeInForce", None)
    if typ in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
        kwargs.pop("price", None)

    # Hedge/One-Way: סניטציה של positionSide ו־reduceOnly
    eff_ps = _effective_position_side_from_kwargs(kwargs)  # עשוי להסיר positionSide
    is_trigger_market = typ in ("STOP_MARKET", "TAKE_PROFIT_MARKET")
    if not _is_hedge_mode_runtime():
        # בחשבון One-Way: לצורך תאימות, ב-*MARKET טריגר עדיף לא לשלוח reduceOnly מלכתחילה
        if is_trigger_market and "reduceOnly" in kwargs:
            kwargs.pop("reduceOnly", None)
        # גם ל-MARKET רגיל היו דיווחי -1106 → ננסה להשאיר ל-retry, אך אם יש closePosition True – אין reduceOnly
        if kwargs.get("closePosition"):
            kwargs.pop("quantity", None)
            kwargs.pop("reduceOnly", None)
    else:
        # Hedge: אם closePosition → אין quantity/reduceOnly
        if kwargs.get("closePosition"):
            kwargs.pop("quantity", None)
            kwargs.pop("reduceOnly", None)

    return _safe_create_order(**kwargs)

def place_stop_market(symbol: str, side: str, stop_price: float, quantity: float, *,
                      reduce_only: bool=True, close_position: bool=False,
                      client_order_id: Optional[str]=None) -> Dict[str, Any]:
    sym = symbol.upper()
    qprice = _quantize_price(sym, float(stop_price))
    qqty   = _quantize_qty(sym, float(quantity))
    kwargs = dict(
        symbol=sym, side=side.upper(), type="STOP_MARKET",
        stopPrice=qprice, recvWindow=RECV_WINDOW, workingType=WORKING_TYPE
    )
    if close_position:
        kwargs["closePosition"] = True
    else:
        kwargs["quantity"] = qqty
        # ב-One-Way והזמנת טריגר MARKET לא נשלח reduceOnly מראש; ב-Hedge זה בסדר
        if reduce_only and _is_hedge_mode_runtime():
            kwargs["reduceOnly"] = True
    if client_order_id:
        kwargs["newClientOrderId"] = _sanitize_coid(client_order_id)
    else:
        kwargs["newClientOrderId"] = _coid("SL", sym)
    return _safe_create_order(**kwargs)

def modify_stop_loss(symbol: str, new_stop_price: float, *,
                     side: Optional[str]=None,
                     client_order_id_prefix: Optional[str]=None,
                     close_position: bool=True,
                     quantity: Optional[float]=None) -> Dict[str, Any]:
    sym = symbol.upper()
    _cancel_closing_orders(sym, types=("STOP", "STOP_MARKET"))
    if not side:
        pos = get_single_position(sym)
        if not pos:
            return {"ok": False, "error": "no_position"}
        amt = float(pos.get("positionAmt","0"))
        side = "SELL" if amt > 0 else "BUY"
    coid = (client_order_id_prefix + "_SL") if client_order_id_prefix else None
    qty = quantity
    if close_position and qty is None:
        pos = get_single_position(sym)
        if not pos:
            return {"ok": False, "error": "no_position_for_close"}
        qty = abs(float(pos.get("positionAmt","0")))
    if qty is None or qty <= 0:
        return {"ok": False, "error": "invalid_qty"}
    return place_stop_market(sym, side, float(new_stop_price), float(qty),
                             reduce_only=True, close_position=bool(close_position),
                             client_order_id=coid)

def place_tp_ladder(symbol: str, entry_side: str, entry_price: float, quantity: float,
                    tp_percents: Optional[List[float]]=None,
                    splits: Optional[List[float]]=None,
                    reduce_only: bool=True,
                    client_order_id_prefix: Optional[str]=None) -> Dict[str, Any]:
    if not LADDER_TP_ENABLE:
        return {"ok": False, "error": "ladder_disabled"}
    now = _now()
    last = _tp_ladder_last_at.get(symbol.upper(), 0.0)
    if (now - last) < TP_LADDER_COOLDOWN_SEC:
        return {"ok": False, "error": "ladder_cooldown"}
    _tp_ladder_last_at[symbol.upper()] = now

    sym = symbol.upper()
    side = "SELL" if entry_side.upper() == "BUY" else "BUY"
    if not tp_percents:
        tp_percents = [float(x) for x in LADDER_TP_DEFAULT_PCTS.split(",") if x.strip()]
    if not splits:
        splits = [float(x) for x in LADDER_TP_DEFAULT_SPLITS.split(",") if x.strip()]
    tp_percents = tp_percents[:LADDER_TP_MAX_LEVELS]
    splits = splits[:len(tp_percents)]
    if abs(sum(splits) - 1.0) > 1e-6:
        s = sum(splits); splits = [x/s for x in splits]

    placed = []; errors = []
    for i, (pct, frac) in enumerate(zip(tp_percents, splits), start=1):
        qty_i = max(0.0, float(quantity) * float(frac))
        if qty_i <= 0: 
            continue
        if entry_side.upper() == "BUY":
            tprice = entry_price * (1.0 + pct/100.0)
        else:
            tprice = entry_price * (1.0 - pct/100.0)

        kwargs = dict(
            symbol=sym,
            side=side,
            type=LADDER_TP_KIND,  # TAKE_PROFIT_MARKET או TAKE_PROFIT
            stopPrice=_quantize_price(sym, float(tprice)),
            closePosition=False,
            quantity=_ensure_min_notional_qty(sym, float(tprice), _quantize_qty(sym, qty_i)),
            workingType=WORKING_TYPE,
            recvWindow=RECV_WINDOW,
            newClientOrderId=_sanitize_coid((client_order_id_prefix or ORDER_ID_PREFIX or "TP") + f"_TP{i}_{sym}")
        )
        # ב-Hedge נעדיף reduceOnly; ב-One-Way ל-*MARKET טריגר לא נוסיף reduceOnly (ול-TAKE_PROFIT Limit זה לא קריטי)
        if reduce_only and _is_hedge_mode_runtime():
            kwargs["reduceOnly"] = True
        res = _safe_create_order(**kwargs)
        if isinstance(res, dict) and res.get("ok") is False and res.get("error"):
            errors.append({"level": i, "error": res.get("error")})
        else:
            placed.append(res)
    return {"ok": len(errors) == 0, "placed": placed, "errors": errors}

def set_breakeven_stop(symbol: str, *, tick_adjust: int = 1) -> Dict[str, Any]:
    sym = symbol.upper()
    pos = get_single_position(sym)
    if not pos:
        return {"ok": False, "error": "no_position"}
    amt = float(pos.get("positionAmt","0"))
    if abs(amt) <= 0:
        return {"ok": False, "error": "zero_amt"}
    entry = float(pos.get("entryPrice") or 0.0)
    if entry <= 0:
        return {"ok": False, "error": "no_entry_price"}

    f = get_symbol_filters(sym) or {}
    tick = float(f.get("tickSize") or DEFAULT_PRICE_TICK_STR)
    if amt > 0:  # LONG
        sprice = entry - tick * max(1, tick_adjust)
        side = "SELL"
    else:       # SHORT
        sprice = entry + tick * max(1, tick_adjust)
        side = "BUY"

    _cancel_closing_orders(sym, types=("STOP", "STOP_MARKET"))
    return place_stop_market(sym, side, sprice, abs(amt), reduce_only=True, close_position=True)

# ===== Klines =====
def get_klines_df(symbol: str, interval: str="5m", limit: int=50):
    try:
        import pandas as pd
    except Exception:
        return None
    try:
        kl = client.futures_klines(symbol=symbol.upper(), interval=interval, limit=min(1000, max(10, limit)))
        cols = ["open_time","open","high","low","close","volume","close_time","qav","trades","tbbav","tbqav","ignore"]
        df = pd.DataFrame(kl, columns=cols)
        for c in ("open","high","low","close","volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
        return df
    except BinanceAPIException as e:
        s = str(e); code = getattr(e, "code", None); status = getattr(e, "status_code", None)
        if "429" in s or "-1003" in s or status == 429 or code in (-1003,):
            logger.warning("get_klines_df rate limited/banned; returning None")
            return None
        logger.error("get_klines_df failed: %s", e); return None
    except Exception as e:
        logger.error("get_klines_df failed: %s", e); return None

# ===== Close-all helper =====
def close_all_positions() -> Dict[str,Any]:
    out = {"closed":[],"errors":[]}
    try:
        for p in get_open_positions():
            sym = p.get("symbol"); amt = float(p.get("positionAmt","0"))
            if abs(amt) <= 1e-12: continue
            side = "SELL" if amt>0 else "BUY"
            try:
                # One-Way עלול לזרוק -1106 על reduceOnly → נשתמש ב-_safe_create_order עם retry פנימי
                res = _safe_create_order(symbol=sym, side=side, type="MARKET",
                                         reduceOnly=True, quantity=_quantize_qty(sym, abs(amt)),
                                         newClientOrderId=_coid("MKT", sym))
                out["closed"].append({"symbol":sym,"qty":abs(amt),"res":res})
            except Exception as e:
                out["errors"].append({"symbol":sym,"err":str(e)})
        return out
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ===== Price facade with WS + coalescing =====
def get_price(symbol: str) -> Optional[float]:
    try:
        if ws_is_fresh and ws_get_price and ws_is_fresh(symbol, int(os.getenv("PRICE_WS_FRESH_TTL", "20"))):
            p = ws_get_price(symbol)
            if p and p > 0:
                return float(p)
    except Exception:
        pass
    p = futures_mark_price(symbol)
    try:
        if p and ws_update_price:
            ws_update_price(symbol, float(p))
    except Exception:
        pass
    return p

def set_leverage(symbol: str, leverage: int) -> Dict[str, Any]:
    try:
        return client.futures_change_leverage(symbol=symbol.upper(), leverage=int(leverage))
    except Exception as e:
        logger.error("Failed to set leverage %s for %s: %s", leverage, symbol, e)
        return {"ok": False, "error": str(e)}

def futures_cancel_and_replace_limit(symbol: str, side: str, price: float, quantity: float, *, reduce_only: bool=False,
                                     client_order_id: Optional[str]=None, time_in_force: str="GTC") -> Dict[str, Any]:
    _cancel_closing_orders(symbol, types=("LIMIT",))
    sym = symbol.upper()
    return futures_create_order(
        symbol=sym,
        side=side.upper(),
        type="LIMIT",
        price=_quantize_price(sym, float(price)),
        quantity=_ensure_min_notional_qty(sym, float(price), _quantize_qty(sym, float(quantity))),
        reduceOnly=bool(reduce_only) if _is_hedge_mode_runtime() else False,
        timeInForce=time_in_force,
        newClientOrderId=_sanitize_coid(client_order_id) if client_order_id else _coid("LMT", sym)
    )

# --- Compatibility wrapper ---
def place_limit_order(
    symbol: str,
    side: str,
    quantity: float | str | None = None,
    price: float | str | None = None,
    *,
    size_usdt: float | str | None = None,
    time_in_force: str = "GTC",
    tif: str | None = None,
    reduce_only: bool = False,
    client=None,
    **kwargs,
):
    sym = symbol.upper()
    if price is None:
        raise ValueError("place_limit_order requires price")

    p_float = float(price)
    qty_str: str | None = None

    if quantity is not None:
        qty_str = _quantize_qty(sym, float(quantity))
    elif size_usdt is not None:
        notional = float(size_usdt)
        computed_qty = max(0.0, notional / max(p_float, 1e-12))
        qty_str = _ensure_min_notional_qty(sym, p_float, _quantize_qty(sym, computed_qty))
    else:
        raise ValueError("place_limit_order requires either quantity or size_usdt")

    if qty_str is None or float(qty_str) <= 0:
        raise ValueError("invalid computed quantity")

    tif_final = (tif or time_in_force or "GTC").upper()

    return futures_create_order(
        symbol=sym,
        side=side.upper(),
        type="LIMIT",
        price=_quantize_price(sym, p_float),
        quantity=qty_str,
        reduceOnly=bool(reduce_only) if _is_hedge_mode_runtime() else False,
        timeInForce=tif_final,
        **{k: v for k, v in kwargs.items() if k not in {"tif"}}
    )

# ===== Public export =====
def get_futures_client() -> Client:
    return client

__all__ = [
    "client","fapi_ping","futures_exchange_info_safe","futures_balance",
    "futures_mark_price","futures_index_price","get_price",
    "get_symbol_info","get_symbol_filters","get_open_positions","futures_open_positions_safe","get_single_position",
    "futures_create_order","place_limit_order","place_stop_market","modify_stop_loss","place_tp_ladder","set_breakeven_stop",
    "futures_cancel_all_orders","futures_cancel_order","get_open_orders","get_all_orders","set_leverage",
    "futures_cancel_and_replace_limit",
    "get_klines_df","close_all_positions","get_futures_client",
    "DEFAULT_QTY_STEP_STR","DEFAULT_PRICE_TICK_STR","DEFAULT_MIN_NOTIONAL",
]


































































































































































































