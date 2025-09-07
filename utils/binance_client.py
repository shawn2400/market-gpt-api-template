# utils/binance_client.py
from __future__ import annotations
import os, time, math, logging
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

WORKING_TYPE = os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE").upper()
RECV_WINDOW = int(os.getenv("BINANCE_RECV_WINDOW", "45000"))

EXINFO_TTL = int(os.getenv("EXCHANGE_INFO_TTL_SEC", "900"))
ORD_BUCKET_WINDOW = int(os.getenv("ORDERS_BUCKET_WINDOW_SEC", "10"))
ORD_QPS_BUCKET = int(os.getenv("ORDERS_QPS_BUCKET", "4"))
BACKOFF_BASE_MS = int(os.getenv("ORDER_BACKOFF_BASE_MS", "120"))
BACKOFF_MAX_MS  = int(os.getenv("ORDER_BACKOFF_MAX_MS",  "1600"))
BINANCE_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "6"))

DEFAULT_QTY_STEP_STR = os.getenv("DEFAULT_QTY_STEP", "0.001")
DEFAULT_PRICE_TICK_STR = os.getenv("DEFAULT_PRICE_TICK", "0.01")
DEFAULT_MIN_NOTIONAL = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

# ===== Ladder ENV (דיפולטים פנימיים בטוחים) =====
LADDER_TP_ENABLE = os.getenv("LADDER_TP_ENABLE", "1") == "1"
LADDER_TP_KIND = os.getenv("LADDER_TP_KIND", "TAKE_PROFIT_MARKET").upper()
LADDER_TP_DEFAULT_PCTS = os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5")
LADDER_TP_DEFAULT_SPLITS = os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25")
LADDER_TP_MAX_LEVELS = int(os.getenv("LADDER_TP_MAX_LEVELS", "5"))

LADDER_SL_ENABLE = os.getenv("LADDER_SL_ENABLE", "0") == "1"
LADDER_SL_DEFAULT_PCTS = os.getenv("LADDER_SL_DEFAULT_PCTS", "")   # דוגמה: "0.7,1.2"
LADDER_SL_MAX_LEVELS = int(os.getenv("LADDER_SL_MAX_LEVELS", "3"))

# קירור TP-Ladder למניעת עומס/כפילויות
TP_LADDER_COOLDOWN_SEC = int(os.getenv("TP_LADDER_COOLDOWN_SEC", "60"))
_tp_ladder_last_at: Dict[str, float] = {}

# ביטול לפי prefix בלבד (כדי לא לגעת בהזמנות לא שלך)
CANCEL_ONLY_PREFIXED_ORDERS = os.getenv("CANCEL_ONLY_PREFIXED_ORDERS", "0") in ("1","true","yes","on")
CANCEL_PREFIX_OVERRIDE = os.getenv("CANCEL_PREFIX_OVERRIDE", "").strip()

# ===== ClientOrderId ENV =====
ORDER_ID_PREFIX = os.getenv("ORDER_ID_PREFIX", "").strip()   # למשל: ALGOGPT
ORDER_ID_SUFFIX = os.getenv("ORDER_ID_SUFFIX", "").strip()
ORDER_ID_INCLUDE_TS = os.getenv("ORDER_ID_INCLUDE_TS", "1").lower() in ("1","true","yes","on")
ORDER_ID_MAXLEN = int(os.getenv("ORDER_ID_MAXLEN", "36"))    # Binance Futures בד"כ עד 36

def _sanitize_coid(s: str) -> str:
    out = []
    for ch in s:
        if ch.isalnum() or ch == "_":
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)[:ORDER_ID_MAXLEN]

def _coid(kind: str, symbol: str, level: int | None = None) -> str:
    """
    מבנה ידידותי לניתוח:
    - ל-TP/SL ladder:  TP1_{SYMBOL}_{ts} / SL2_{SYMBOL}_{ts}
    - לשאר:           KIND_{SYMBOL}_{ts}
    תומך ב-Prefix/Suffix ו-Timestamp לפי ENV.
    """
    k = kind.upper()
    if level is not None and k in ("TP", "SL"):
        k = f"{k}{level}"  # TP1 / SL2 ...

    parts = []
    if ORDER_ID_PREFIX:
        parts.append(ORDER_ID_PREFIX)
    parts.append(k)
    parts.append(symbol.upper())
    # אם לא TP/SL עם level – תוסיף level נפרד (נדיר)
    if level is not None and kind.upper() not in ("TP", "SL"):
        parts.append(str(level))
    if ORDER_ID_INCLUDE_TS:
        parts.append(str(int(time.time() * 1000)))
    if ORDER_ID_SUFFIX:
        parts.append(ORDER_ID_SUFFIX)
    return _sanitize_coid("_".join(parts))

def _kind_from_kwargs(kwargs: dict) -> str:
    t = str(kwargs.get("type", "")).upper()
    if "TAKE_PROFIT" in t:
        return "TP"
    if "STOP" in t:
        return "SL"
    if t == "MARKET":
        return "MKT"
    if t == "LIMIT":
        return "LMT"
    return "ORD"

# ===== Init Futures client =====
client = Client(API_KEY, API_SECRET)
client.API_URL = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

# ===== Caches =====
_exinfo_cache: Dict[str, Any] = {"ts": 0.0, "data": None}
def _now() -> float: return time.time()

def _get_exchange_info_cached() -> Optional[Dict[str, Any]]:
    ts = _now()
    if _exinfo_cache["data"] and (ts - _exinfo_cache["ts"] < EXINFO_TTL):
        return _exinfo_cache["data"]
    try:
        data = client.futures_exchange_info()
        _exinfo_cache["data"] = data; _exinfo_cache["ts"] = ts
        return data
    except Exception as e:
        logger.error("futures_exchange_info failed: %s", e)
        return _exinfo_cache["data"]

# ========== Core ==========
def fapi_ping() -> bool:
    try: client.futures_ping(); return True
    except Exception as e: logger.warning("Futures ping failed: %s", e); return False

def futures_exchange_info_safe() -> Optional[Dict[str, Any]]: return _get_exchange_info_cached()

def futures_balance() -> List[Dict[str, Any]]:
    try: return client.futures_account_balance() or []
    except Exception as e: logger.error("Failed to fetch futures_balance: %s", e); return []

def futures_mark_price(symbol: str) -> Optional[float]:
    try: return float(client.futures_mark_price(symbol=symbol.upper())["markPrice"])
    except Exception as e: logger.error("Failed mark price for %s: %s", symbol, e); return None

def get_price(symbol: str) -> Optional[float]: return futures_mark_price(symbol)

def get_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    info = futures_exchange_info_safe()
    if not info: return None
    su = symbol.upper()
    for s in info.get("symbols", []):
        if (s.get("symbol") or "").upper() == su: return s
    return None

def get_symbol_filters(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        si = get_symbol_info(symbol)
        if not si: return None
        filters = {"minQty": None, "stepSize": None, "tickSize": None, "minNotional": None}
        for f in si.get("filters", []):
            t = f.get("filterType")
            if t == "LOT_SIZE":
                filters["minQty"] = f.get("minQty"); filters["stepSize"] = f.get("stepSize")
            elif t == "PRICE_FILTER":
                filters["tickSize"] = f.get("tickSize")
            elif t in ("MIN_NOTIONAL", "NOTIONAL"):
                filters["minNotional"] = f.get("notional") or f.get("minNotional")
        return filters
    except Exception as e:
        logger.error("Failed get_symbol_filters: %s", e); return None

# ========== Precision ==========
def _decimals_from_step(step_str: str) -> int:
    if "." not in step_str: return 0
    frac = step_str.split(".")[1]
    while frac and frac.endswith("0"): frac = frac[:-1]
    return len(frac)

def _quantize_price(symbol: str, price: float) -> str:
    f = get_symbol_filters(symbol) or {}
    tick = float(f.get("tickSize") or DEFAULT_PRICE_TICK_STR)
    if tick <= 0: tick = float(DEFAULT_PRICE_TICK_STR)
    steps = round(price / tick); adj = steps * tick
    decs = _decimals_from_step(str(f.get("tickSize") or DEFAULT_PRICE_TICK_STR))
    return f"{adj:.{decs}f}"

def _quantize_qty(symbol: str, qty: float) -> str:
    f = get_symbol_filters(symbol) or {}
    step = float(f.get("stepSize") or DEFAULT_QTY_STEP_STR)
    if step <= 0: step = float(DEFAULT_QTY_STEP_STR)
    steps = math.floor(qty / step); adj = max(step, steps * step)
    decs = _decimals_from_step(str(f.get("stepSize") or DEFAULT_QTY_STEP_STR))
    return f"{adj:.{decs}f}"

def _ensure_min_notional(symbol: str, price: float, qty: float) -> float:
    f = get_symbol_filters(symbol) or {}
    min_notional = float(f.get("minNotional") or DEFAULT_MIN_NOTIONAL)
    notional = price * qty
    if notional >= min_notional: return qty
    return min_notional / max(price, 1e-12)

def _ensure_min_notional_qty(symbol: str, price: float, qty_str: str) -> str:
    qf = float(qty_str); need = _ensure_min_notional(symbol, price, qf)
    if need <= qf + 1e-12: return qty_str
    return _quantize_qty(symbol, need)

# ========== Auto-tune QPS/Backoff ==========
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

# ========== Helper: prefix match for cancel ==========
def _order_has_prefix(o: Dict[str, Any], prefix: str) -> bool:
    if not prefix: 
        return True
    coid = str(o.get("clientOrderId") or o.get("origClientOrderId") or "")
    return coid.startswith(prefix)

def _cancel_closing_orders(symbol: str, types: Iterable[str]) -> int:
    """
    אם CANCEL_ONLY_PREFIXED_ORDERS=1 – נבטל רק הזמנות עם prefix מתאים
    (CANCEL_PREFIX_OVERRIDE או ORDER_ID_PREFIX).
    """
    open_orders = get_open_orders(symbol); count = 0
    tset = set(t.upper() for t in types)
    prefix = (CANCEL_PREFIX_OVERRIDE or ORDER_ID_PREFIX or "").strip()
    only_pref = CANCEL_ONLY_PREFIXED_ORDERS
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

# ========== Positions ==========
def get_open_positions(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        acc_info = client.futures_account()
        positions = acc_info.get("positions", []); out = []
        for pos in positions:
            amt = float(pos.get("positionAmt", "0"))
            if abs(amt) > 1e-12 and (symbol is None or (pos.get("symbol") or "").upper() == symbol.upper()):
                out.append(pos)
        return out
    except Exception as e:
        logger.error("Failed to get open positions: %s", e); return []

def futures_open_positions_safe(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    return get_open_positions(symbol)

def get_single_position(symbol: str) -> Optional[Dict[str, Any]]:
    for p in get_open_positions(symbol): return p
    return None

def _position_side_from_amt(amt: float) -> str: return "LONG" if amt > 0 else "SHORT"

def _order_side_for_close(pos_side: str) -> str:
    ps = (pos_side or "").upper()
    if ps == "LONG":  return "SELL"
    if ps == "SHORT": return "BUY"
    return "SELL"

# ========== Orders ==========
def _safe_create_order(**kwargs) -> Dict[str, Any]:
    kwargs.setdefault("workingType", WORKING_TYPE)
    kwargs.setdefault("recvWindow", RECV_WINDOW)

    # הזרקת ClientOrderId אוטומטי אם לא ניתן
    if not str(kwargs.get("newClientOrderId", "")).strip():
        sym = str(kwargs.get("symbol", "UNK")).upper()
        kind = _kind_from_kwargs(kwargs)
        kwargs["newClientOrderId"] = _coid(kind, sym)

    for attempt in range(1, BINANCE_MAX_RETRIES + 1):
        if not _rate_allow():
            _backoff_sleep(attempt); continue
        try:
            return client.futures_create_order(**kwargs)
        except BinanceAPIException as e:
            s = str(e); code = getattr(e, "code", None); status = getattr(e, "status_code", None)
            if "429" in s or "-1003" in s or status == 429 or code in (-1003,):
                logger.warning("Rate-limited, attempt=%s; qps=%s base=%sms", attempt, _dyn_qps, _dyn_backoff_base)
                _note_rate_limit_hit(); _backoff_sleep(attempt); continue
            logger.error("BinanceAPIException: %s", e)
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.error("futures_create_order failed: %s", e)
            _backoff_sleep(attempt)
            if attempt == BINANCE_MAX_RETRIES:
                return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "max_retries_exceeded"}

def futures_create_order(**kwargs) -> Dict[str, Any]: return _safe_create_order(**kwargs)

def futures_cancel_all_orders(symbol: str) -> Dict[str, Any]:
    try: return client.futures_cancel_all_open_orders(symbol=symbol.upper())
    except Exception as e: logger.error("Failed to cancel orders for %s: %s", symbol, e); return {"ok": False, "error": str(e)}

def futures_cancel_order(symbol: str, orderId: int | str) -> Dict[str, Any]:
    try: return client.futures_cancel_order(symbol=symbol.upper(), orderId=orderId)
    except Exception as e: logger.error("Failed to cancel order %s/%s: %s", symbol, orderId, e); return {"ok": False, "error": str(e)}

def get_open_orders(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        if symbol: return client.futures_get_open_orders(symbol=symbol.upper()) or []
        return client.futures_get_open_orders() or []
    except Exception as e:
        logger.error("Failed to get open orders: %s", e); return []

def set_leverage(symbol: str, leverage: int) -> Dict[str, Any]:
    try: return client.futures_change_leverage(symbol=symbol.upper(), leverage=int(leverage))
    except Exception as e: logger.error("Failed to set leverage %s for %s: %s", leverage, symbol, e); return {"ok": False, "error": str(e)}

# ========== Cancel+Recreate ==========
def _compute_partial_qty(symbol: str, pos_amt: float, pct: Optional[float], qty: Optional[float]) -> Tuple[bool, str]:
    if pct is None and qty is None: return False, ""
    target = 0.0
    if pct is not None:
        pct = max(0.0, min(1.0, float(pct))); target = max(0.0, abs(pos_amt) * pct)
    if qty is not None:
        target = target if target > 0 else qty; target = min(target, abs(pos_amt))
    q = float(_quantize_qty(symbol, target))
    if q <= 0: raise ValueError("quantity rounds to zero")
    return True, _quantize_qty(symbol, q)

def modify_stop_loss(symbol: str, new_sl_price: float, position_side: Optional[str] = None,
                     pct: Optional[float] = None, quantity: Optional[float] = None) -> Dict[str, Any]:
    try:
        pos = get_single_position(symbol)
        if not pos: return {"ok": False, "error": f"No open position for {symbol}"}
        amt = float(pos.get("positionAmt") or 0.0)
        if abs(amt) < 1e-12: return {"ok": False, "error": f"No non-zero position for {symbol}"}
        pos_side = position_side or _position_side_from_amt(amt)
        side = _order_side_for_close(pos_side)
        qprice = _quantize_price(symbol, float(new_sl_price))
        price_f = float(qprice)
        canceled = _cancel_closing_orders(symbol, types=("STOP", "STOP_MARKET"))
        is_partial, qstr = _compute_partial_qty(symbol, amt, pct, quantity)
        if is_partial:
            qstr = _ensure_min_notional_qty(symbol, price_f, qstr)
            order = _safe_create_order(symbol=symbol.upper(), side=side, type="STOP_MARKET",
                                       stopPrice=qprice, reduceOnly=True, quantity=qstr,
                                       newClientOrderId=_coid("SL", symbol))
        else:
            order = _safe_create_order(symbol=symbol.upper(), side=side, type="STOP_MARKET",
                                       stopPrice=qprice, reduceOnly=True, closePosition=True,
                                       newClientOrderId=_coid("SL", symbol))
        return {"ok": True, "canceled": canceled, "order": order, "stopPrice": qprice}
    except BinanceAPIException as e:
        logger.error("modify_stop_loss failed: %s", e); return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("modify_stop_loss failed: %s", e); return {"ok": False, "error": str(e)}

def modify_take_profit(symbol: str, new_tp_price: float, position_side: Optional[str] = None,
                       pct: Optional[float] = None, quantity: Optional[float] = None) -> Dict[str, Any]:
    try:
        pos = get_single_position(symbol)
        if not pos: return {"ok": False, "error": f"No open position for {symbol}"}
        amt = float(pos.get("positionAmt") or 0.0)
        if abs(amt) < 1e-12: return {"ok": False, "error": f"No non-zero position for {symbol}"}
        pos_side = position_side or _position_side_from_amt(amt)
        side = _order_side_for_close(pos_side)
        qprice = _quantize_price(symbol, float(new_tp_price))
        price_f = float(qprice)
        canceled = _cancel_closing_orders(symbol, types=("TAKE_PROFIT", "TAKE_PROFIT_MARKET"))
        is_partial, qstr = _compute_partial_qty(symbol, amt, pct, quantity)
        if is_partial:
            qstr = _ensure_min_notional_qty(symbol, price_f, qstr)
            order = _safe_create_order(symbol=symbol.upper(), side=side, type="TAKE_PROFIT_MARKET",
                                       stopPrice=qprice, reduceOnly=True, quantity=qstr,
                                       newClientOrderId=_coid("TP", symbol))
        else:
            order = _safe_create_order(symbol=symbol.upper(), side=side, type="TAKE_PROFIT_MARKET",
                                       stopPrice=qprice, reduceOnly=True, closePosition=True,
                                       newClientOrderId=_coid("TP", symbol))
        return {"ok": True, "canceled": canceled, "order": order, "stopPrice": qprice}
    except BinanceAPIException as e:
        logger.error("modify_take_profit failed: %s", e); return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("modify_take_profit failed: %s", e); return {"ok": False, "error": str(e)}

def set_breakeven_stop(symbol: str, offset_bps: float = 0.0) -> Dict[str, Any]:
    pos = get_single_position(symbol)
    if not pos: return {"ok": False, "error": f"No open position for {symbol}"}
    entry = float(pos.get("entryPrice") or 0.0)
    if entry <= 0: return {"ok": False, "error": f"Invalid entryPrice for {symbol}"}
    amt = float(pos.get("positionAmt", "0"))
    pos_side = _position_side_from_amt(amt)
    sl = entry * (1.0 + (offset_bps / 10000.0)) if pos_side == "LONG" else entry * (1.0 - (offset_bps / 10000.0))
    return modify_stop_loss(symbol, sl, position_side=pos_side)

# ========== Ladder ==========
def clear_take_profit_orders(symbol: str) -> int:
    return _cancel_closing_orders(symbol, types=("TAKE_PROFIT", "TAKE_PROFIT_MARKET"))

def clear_stop_orders(symbol: str) -> int:
    return _cancel_closing_orders(symbol, types=("STOP", "STOP_MARKET"))

def _normalize_splits(splits: List[float], levels: int) -> List[float]:
    if not splits or len(splits) != levels: return [1.0 / levels] * levels
    s = [max(0.0, float(x)) for x in splits]; tot = sum(s)
    if tot <= 0: return [1.0 / levels] * levels
    return [x / tot for x in s]

def _build_tp_prices_by_pct(entry: float, pos_side: str, pcts: List[float]) -> List[float]:
    out = []
    for p in pcts:
        p = float(p)
        out.append(entry * (1.0 + p/100.0) if pos_side=="LONG" else entry * (1.0 - p/100.0))
    return out

def place_tp_ladder(symbol: str, targets_prices: Optional[List[float]] = None, splits: Optional[List[float]] = None,
                    *, position_side: Optional[str] = None, percent_targets: Optional[List[float]] = None) -> Dict[str, Any]:
    if not LADDER_TP_ENABLE: return {"ok": False, "error": "TP ladder disabled by ENV"}

    # קירור למניעת כפילויות/עומס
    now = _now(); su = symbol.upper()
    last = _tp_ladder_last_at.get(su, 0.0)
    if now - last < max(0, TP_LADDER_COOLDOWN_SEC):
        return {"ok": False, "cooldown": True, "wait_sec": int(TP_LADDER_COOLDOWN_SEC - (now - last))}
    _tp_ladder_last_at[su] = now

    pos = get_single_position(symbol)
    if not pos: return {"ok": False, "error": f"No open position for {symbol}"}
    amt = abs(float(pos.get("positionAmt") or 0.0))
    if amt <= 0: return {"ok": False, "error": "No non-zero position"}
    entry = float(pos.get("entryPrice") or 0.0)
    pos_side = position_side or _position_side_from_amt(float(pos.get("positionAmt") or 0.0))
    side = _order_side_for_close(pos_side)

    if percent_targets and len(percent_targets) > 0:
        prices = _build_tp_prices_by_pct(entry, pos_side, percent_targets)
    elif targets_prices and len(targets_prices) > 0:
        prices = [float(p) for p in targets_prices]
    else:
        s = (LADDER_TP_DEFAULT_PCTS or "1.8,3.2,5.5")
        pcts = [float(x) for x in s.split(",") if x.strip()]
        prices = _build_tp_prices_by_pct(entry, pos_side, pcts)

    prices = prices[: max(1, min(LADDER_TP_MAX_LEVELS, len(prices)))]
    levels = len(prices)

    if splits is None:
        ss = (LADDER_TP_DEFAULT_SPLITS or "0.4,0.35,0.25")
        splits = [float(x) for x in ss.split(",") if x.strip()]
    splits = _normalize_splits(splits or [], levels)

    canceled = clear_take_profit_orders(symbol)

    results = []; qty_left = amt
    for i, (p, sp) in enumerate(zip(prices, splits), start=1):
        qprice = _quantize_price(symbol, float(p))
        price_f = float(qprice)
        is_last = (i == levels)
        if not is_last:
            qi = float(_quantize_qty(symbol, amt * sp))
            qi = min(qi, qty_left)
            if qi <= 0: continue
            qi = float(_ensure_min_notional(symbol, price_f, qi))
            qstr = _quantize_qty(symbol, qi)
            qty_left = max(0.0, qty_left - float(qstr))
            order = _safe_create_order(symbol=symbol.upper(), side=side,
                                       type=LADDER_TP_KIND, stopPrice=qprice,
                                       reduceOnly=True, quantity=qstr,
                                       newClientOrderId=_coid("TP", symbol, i))
        else:
            order = _safe_create_order(symbol=symbol.upper(), side=side,
                                       type=LADDER_TP_KIND, stopPrice=qprice,
                                       reduceOnly=True, closePosition=True,
                                       newClientOrderId=_coid("TP", symbol, i))
        results.append({"level": i, "stopPrice": qprice, "resp": order})
    return {"ok": True, "canceled": canceled, "levels": results, "side": pos_side}

def place_sl_ladder(symbol: str, stops_prices: Optional[List[float]] = None, splits: Optional[List[float]] = None,
                    *, position_side: Optional[str] = None, percent_stops: Optional[List[float]] = None) -> Dict[str, Any]:
    if not LADDER_SL_ENABLE: return {"ok": False, "error": "SL ladder disabled by ENV"}
    pos = get_single_position(symbol)
    if not pos: return {"ok": False, "error": f"No open position for {symbol}"}
    amt = abs(float(pos.get("positionAmt") or 0.0))
    if amt <= 0: return {"ok": False, "error": "No non-zero position"}
    entry = float(pos.get("entryPrice") or 0.0)
    pos_side = position_side or _position_side_from_amt(float(pos.get("positionAmt") or 0.0))
    side = _order_side_for_close(pos_side)

    if percent_stops:
        prices = []
        for pct in percent_stops:
            pct = abs(float(pct))
            prices.append(entry * (1.0 - pct/100.0) if pos_side=="LONG" else entry * (1.0 + pct/100.0))
    elif stops_prices:
        prices = [float(x) for x in stops_prices]
    else:
        if not (LADDER_SL_DEFAULT_PCTS or "").strip(): return {"ok": False, "error": "No SL percentages provided"}
        pcts = [float(x) for x in LADDER_SL_DEFAULT_PCTS.split(",") if x.strip()]
        prices = []
        for pct in pcts:
            pct = abs(float(pct))
            prices.append(entry * (1.0 - pct/100.0) if pos_side=="LONG" else entry * (1.0 + pct/100.0))

    prices = prices[: max(1, min(LADDER_SL_MAX_LEVELS, len(prices)))]
    levels = len(prices)

    if splits is None: splits = [1.0 / levels] * levels
    splits = _normalize_splits(splits, levels)

    canceled = clear_stop_orders(symbol)

    results = []; qty_left = amt
    for i, (p, sp) in enumerate(zip(prices, splits), start=1):
        qprice = _quantize_price(symbol, float(p))
        price_f = float(qprice)
        is_last = (i == levels)
        if not is_last:
            qi = float(_quantize_qty(symbol, amt * sp))
            qi = min(qi, qty_left)
            if qi <= 0: continue
            qi = float(_ensure_min_notional(symbol, price_f, qi))
            qstr = _quantize_qty(symbol, qi)
            qty_left = max(0.0, qty_left - float(qstr))
            order = _safe_create_order(symbol=symbol.upper(), side=side, type="STOP_MARKET",
                                       stopPrice=qprice, reduceOnly=True, quantity=qstr,
                                       newClientOrderId=_coid("SL", symbol, i))
        else:
            order = _safe_create_order(symbol=symbol.upper(), side=side, type="STOP_MARKET",
                                       stopPrice=qprice, reduceOnly=True, closePosition=True,
                                       newClientOrderId=_coid("SL", symbol, i))
        results.append({"level": i, "stopPrice": qprice, "resp": order})
    return {"ok": True, "canceled": canceled, "levels": results, "side": pos_side}

# ========== extras ==========
def get_klines_df(symbol: str, interval: str="5m", limit: int=50):
    try:
        import pandas as pd
    except Exception:
        return None
    try:
        kl = client.futures_klines(symbol=symbol.upper(), interval=interval, limit=min(1000, max(10, limit)))
        cols = ["open_time","open","high","low","close","volume","close_time","qav","trades","tbbav","tbqav","ignore"]
        df = pd.DataFrame(kl, columns=cols)
        for c in ("open","high","low","close","volume"): df[c] = df[c].astype(float)
        return df
    except Exception as e:
        logger.error("get_klines_df failed: %s", e); return None

def close_all_positions() -> Dict[str,Any]:
    out = {"closed":[],"errors":[]}
    try:
        for p in get_open_positions():
            sym = p.get("symbol"); amt = float(p.get("positionAmt","0"))
            if abs(amt) <= 1e-12: continue
            side = "SELL" if amt>0 else "BUY"
            try:
                res = _safe_create_order(symbol=sym, side=side, type="MARKET",
                                         reduceOnly=True, quantity=_quantize_qty(sym, abs(amt)),
                                         newClientOrderId=_coid("MKT", sym))
                out["closed"].append({"symbol":sym,"qty":abs(amt),"res":res})
            except Exception as e:
                out["errors"].append({"symbol":sym,"err":str(e)})
        return out
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_futures_client() -> Client: return client

__all__ = [
    "client","fapi_ping","futures_exchange_info_safe","futures_balance","futures_mark_price","get_price",
    "get_symbol_info","get_symbol_filters","get_open_positions","futures_open_positions_safe","get_single_position",
    "futures_create_order","futures_cancel_all_orders","futures_cancel_order","get_open_orders","set_leverage",
    "modify_stop_loss","modify_take_profit","set_breakeven_stop","clear_take_profit_orders","clear_stop_orders",
    "place_tp_ladder","place_sl_ladder","get_klines_df","close_all_positions","get_futures_client",
    "DEFAULT_QTY_STEP_STR","DEFAULT_PRICE_TICK_STR","DEFAULT_MIN_NOTIONAL",
]























































































































































































