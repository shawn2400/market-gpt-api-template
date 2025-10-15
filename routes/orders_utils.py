# routes/orders_utils.py
from __future__ import annotations
from typing import Any, Callable, List, Optional, Tuple
import hmac

__all__ = [
    "csv_list",
    "norm_upper",
    "as_float",
    "as_int",
    "filter_by_status",
    "filter_by_side",
    "fetch_orders_multi",
    "sort_key_factory",
    "apply_sort",
    "filter_price_range",
    "filter_qty_range",
    "filter_time_range",
    "filter_client_order_id",
    "token_ok",
]

def csv_list(val: Optional[str]) -> List[str]:
    if not val:
        return []
    return [x.strip() for x in str(val).split(",") if x.strip()]

def norm_upper(x: Optional[str]) -> str:
    return (x or "").strip().upper()

def as_float(v: Any) -> float:
    try:
        if v is None:
            return float("nan")
        return float(v)
    except Exception:
        try:
            return float(str(v))
        except Exception:
            return float("nan")

def as_int(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return 0

def filter_by_status(orders: List[dict], statuses: List[str]) -> List[dict]:
    if not statuses:
        return orders
    want = {s.upper() for s in statuses if s}
    out: List[dict] = []
    for o in orders:
        st = norm_upper(o.get("status"))
        if not want or st in want:
            out.append(o)
    return out

def filter_by_side(orders: List[dict], sides: List[str]) -> List[dict]:
    if not sides:
        return orders
    want = {s.upper() for s in sides if s}
    out: List[dict] = []
    for o in orders:
        sd = norm_upper(o.get("side"))
        if not want or sd in want:
            out.append(o)
    return out

def fetch_orders_multi(symbols: List[str]) -> List[dict]:
    try:
        from utils.binance_client import get_open_orders  # type: ignore
    except Exception as e:
        raise RuntimeError(f"binance_client unavailable: {e}")
    all_rows: List[dict] = []
    if not symbols:
        return get_open_orders(None) or []
    for s in symbols:
        rows = get_open_orders(s) or []
        all_rows.extend(rows)
    return all_rows

def sort_key_factory(field: str) -> Callable[[dict], Tuple]:
    f = field.strip()
    fu = f.upper()

    def k(o: dict) -> Tuple:
        raw = {
            "orderId": o.get("orderId"),
            "symbol": o.get("symbol"),
            "side": o.get("side"),
            "type": o.get("type"),
            "status": o.get("status"),
            "reduceOnly": o.get("reduceOnly"),
            "timeInForce": o.get("timeInForce"),
            "activatePrice": o.get("activatePrice"),
            "priceRate": o.get("priceRate"),
            "price": o.get("price") or o.get("avgPrice"),
            "origQty": o.get("origQty") or o.get("orig_quantity") or o.get("quantity"),
            "executedQty": o.get("executedQty") or o.get("executed_quantity"),
            "clientOrderId": o.get("clientOrderId") or o.get("origClientOrderId"),
            "updateTime": o.get("updateTime") or o.get("time"),
            "time": o.get("time") or o.get("updateTime"),
        }
        if fu in ("UPDATETIME", "TIME"):
            return (as_int(raw["updateTime"] or raw["time"]),)
        if fu == "ORDERID":
            return (as_int(raw["orderId"]),)
        if fu == "PRICE":
            return (as_float(raw["price"]),)
        if fu in ("ORIGQTY", "QTY"):
            return (as_float(raw["origQty"]),)
        if fu in ("EXECUTEDQTY",):
            return (as_float(raw["executedQty"]),)
        if fu == "REDUCEONLY":
            return (1 if raw["reduceOnly"] else 0,)
        if fu in ("SYMBOL", "SIDE", "TYPE", "STATUS", "CLIENTORDERID", "TIMEINFORCE"):
            v = (
                raw["symbol"]
                if fu == "SYMBOL" else raw["side"]
                if fu == "SIDE" else raw["type"]
                if fu == "TYPE" else raw["status"]
                if fu == "STATUS" else raw["clientOrderId"]
                if fu == "CLIENTORDERID" else raw["timeInForce"]
            )
            return (str(v or ""),)
        return (str(raw.get(f, "") or ""),)

    return k

def apply_sort(orders: List[dict], sort_fields: List[str], order: str) -> List[dict]:
    if not sort_fields:
        sort_fields = ["updateTime"]
    direction_desc = (str(order or "desc").lower() in ("desc", "descending", "down"))
    out = list(orders)
    for fld in reversed(sort_fields):
        keyfn = sort_key_factory(fld)
        out.sort(key=keyfn, reverse=direction_desc)
    return out

def filter_price_range(orders: List[dict], min_price: Optional[float], max_price: Optional[float]) -> List[dict]:
    if min_price is None and max_price is None:
        return orders
    lo = float(min_price) if min_price is not None else None
    hi = float(max_price) if max_price is not None else None
    out: List[dict] = []
    for o in orders:
        p = as_float(o.get("price") or o.get("avgPrice"))
        if (p != p):  # NaN
            continue
        if lo is not None and p < lo:
            continue
        if hi is not None and p > hi:
            continue
        out.append(o)
    return out

def filter_qty_range(orders: List[dict], min_qty: Optional[float], max_qty: Optional[float]) -> List[dict]:
    if min_qty is None and max_qty is None:
        return orders
    lo = float(min_qty) if min_qty is not None else None
    hi = float(max_qty) if max_qty is not None else None
    out: List[dict] = []
    for o in orders:
        q = as_float(o.get("origQty") or o.get("orig_quantity") or o.get("quantity"))
        if (q != q):  # NaN
            continue
        if lo is not None and q < lo:
            continue
        if hi is not None and q > hi:
            continue
        out.append(o)
    return out

def filter_time_range(orders: List[dict], since_ts: Optional[int], until_ts: Optional[int]) -> List[dict]:
    if since_ts is None and until_ts is None:
        return orders
    lo = int(since_ts) if since_ts is not None else None
    hi = int(until_ts) if until_ts is not None else None
    out: List[dict] = []
    for o in orders:
        ts = as_int(o.get("updateTime") or o.get("time"))
        if lo is not None and ts < lo:
            continue
        if hi is not None and ts > hi:
            continue
        out.append(o)
    return out

def filter_client_order_id(orders: List[dict], exact: Optional[str], like: Optional[str]) -> List[dict]:
    if not exact and not like:
        return orders
    ex = (exact or "").strip()
    lk = (like or "").strip().lower()
    out: List[dict] = []
    for o in orders:
        coid = (o.get("clientOrderId") or o.get("origClientOrderId") or "")
        if ex and coid == ex:
            out.append(o); continue
        if lk and lk in str(coid).lower():
            out.append(o); continue
    return out

def token_ok(header: Optional[str], expected: str) -> bool:
    """
    Timing-safe Bearer token verify.
    If expected is empty -> allow (no protection configured).
    """
    if not expected:
        return True
    if not header or not header.startswith("Bearer "):
        return False
    got = header.split(" ", 1)[1].strip()
    try:
        # timing-safe compare
        return hmac.compare_digest(got, expected)
    except Exception:
        return False
