# orders_utils.py
from __future__ import annotations
from typing import Any, Callable, List, Optional, Tuple

__all__ = [
    "_csv_list",
    "_norm_upper",
    "_as_float",
    "_as_int",
    "_filter_by_status",
    "_filter_by_side",
    "_fetch_orders_multi",
    "_sort_key_factory",
    "_apply_sort",
    "_filter_price_range",
    "_filter_qty_range",
    "_filter_time_range",
    "_filter_client_order_id",
]

def _csv_list(val: Optional[str]) -> List[str]:
    if not val:
        return []
    return [x.strip() for x in str(val).split(",") if x.strip()]

def _norm_upper(x: Optional[str]) -> str:
    return (x or "").strip().upper()

def _as_float(v: Any) -> float:
    try:
        if v is None:
            return float("nan")
        return float(v)
    except Exception:
        try:
            return float(str(v))
        except Exception:
            return float("nan")

def _as_int(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return 0

def _filter_by_status(orders: List[dict], statuses: List[str]) -> List[dict]:
    if not statuses:
        return orders
    want = {s.upper() for s in statuses if s}
    out: List[dict] = []
    for o in orders:
        st = _norm_upper(o.get("status"))
        if not want or st in want:
            out.append(o)
    return out

def _filter_by_side(orders: List[dict], sides: List[str]) -> List[dict]:
    if not sides:
        return orders
    want = {s.upper() for s in sides if s}
    out: List[dict] = []
    for o in orders:
        sd = _norm_upper(o.get("side"))
        if not want or sd in want:
            out.append(o)
    return out

def _fetch_orders_multi(symbols: List[str]) -> List[dict]:
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

def _sort_key_factory(field: str) -> Callable[[dict], Tuple]:
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
            return (_as_int(raw["updateTime"] or raw["time"]),)
        if fu == "ORDERID":
            return (_as_int(raw["orderId"]),)
        if fu == "PRICE":
            return (_as_float(raw["price"]),)
        if fu in ("ORIGQTY", "QTY"):
            return (_as_float(raw["origQty"]),)
        if fu in ("EXECUTEDQTY",):
            return (_as_float(raw["executedQty"]),)
        if fu == "REDUCEONLY":
            return (1 if raw["reduceOnly"] else 0,)
        if fu in ("SYMBOL","SIDE","TYPE","STATUS","CLIENTORDERID","TIMEINFORCE"):
            v = raw["symbol"] if fu=="SYMBOL" else \
                raw["side"] if fu=="SIDE" else \
                raw["type"] if fu=="TYPE" else \
                raw["status"] if fu=="STATUS" else \
                raw["clientOrderId"] if fu=="CLIENTORDERID" else \
                raw["timeInForce"]
            return (str(v or ""),)
        return (str(raw.get(f, "") or ""),)
    return k

def _apply_sort(orders: List[dict], sort_fields: List[str], order: str) -> List[dict]:
    if not sort_fields:
        sort_fields = ["updateTime"]
    direction_desc = (str(order or "desc").lower() in ("desc", "descending", "down"))
    out = list(orders)
    for fld in reversed(sort_fields):
        keyfn = _sort_key_factory(fld)
        out.sort(key=keyfn, reverse=direction_desc)
    return out

def _filter_price_range(orders: List[dict], min_price: Optional[float], max_price: Optional[float]) -> List[dict]:
    if min_price is None and max_price is None:
        return orders
    lo = float(min_price) if min_price is not None else None
    hi = float(max_price) if max_price is not None else None
    out: List[dict] = []
    for o in orders:
        p = _as_float(o.get("price") or o.get("avgPrice"))
        if (p != p):  # NaN
            continue
        if lo is not None and p < lo:
            continue
        if hi is not None and p > hi:
            continue
        out.append(o)
    return out

def _filter_qty_range(orders: List[dict], min_qty: Optional[float], max_qty: Optional[float]) -> List[dict]:
    if min_qty is None and max_qty is None:
        return orders
    lo = float(min_qty) if min_qty is not None else None
    hi = float(max_qty) if max_qty is not None else None
    out: List[dict] = []
    for o in orders:
        q = _as_float(o.get("origQty") or o.get("orig_quantity") or o.get("quantity"))
        if (q != q):  # NaN
            continue
        if lo is not None and q < lo:
            continue
        if hi is not None and q > hi:
            continue
        out.append(o)
    return out

def _filter_time_range(orders: List[dict], since_ts: Optional[int], until_ts: Optional[int]) -> List[dict]:
    if since_ts is None and until_ts is None:
        return orders
    lo = int(since_ts) if since_ts is not None else None
    hi = int(until_ts) if until_ts is not None else None
    out: List[dict] = []
    for o in orders:
        ts = _as_int(o.get("updateTime") or o.get("time"))
        if lo is not None and ts < lo:
            continue
        if hi is not None and ts > hi:
            continue
        out.append(o)
    return out

def _filter_client_order_id(orders: List[dict], exact: Optional[str], like: Optional[str]) -> List[dict]:
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
