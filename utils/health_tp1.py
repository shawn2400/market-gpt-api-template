# utils/health_tp1.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
from typing import Dict, Any, List, Optional, Tuple
from contextlib import suppress

from utils.binance_client import get_all_orders, futures_mark_price

TP_STATUSES = {"NEW", "PARTIALLY_FILLED"}
TP_TYPES = {"TAKE_PROFIT", "TAKE_PROFIT_MARKET"}
SL_TYPES = {"STOP", "STOP_MARKET"}

def _env_tags() -> List[str]:
    raw = os.getenv("TP1_TAGS", "TP1,tp1,tp_1,TAKE_PROFIT_1")
    return [t.strip() for t in str(raw).split(",") if t.strip()]

def _is_tp_order(o: Dict[str, Any]) -> bool:
    typ = (o.get("type") or "").upper()
    st  = (o.get("status") or "").upper()
    return (typ in TP_TYPES) and (st in TP_STATUSES)

def _is_sl_order(o: Dict[str, Any]) -> bool:
    typ = (o.get("type") or "").upper()
    st  = (o.get("status") or "").upper()
    return (typ in SL_TYPES) and (st in TP_STATUSES)

def _has_tp1_tag(o: Dict[str, Any], tags: List[str]) -> bool:
    coid = str(o.get("clientOrderId") or "")
    return any(t in coid for t in tags)

def _price_float(v: Any) -> Optional[float]:
    with suppress(Exception):
        if v is None: return None
        return float(v)
    return None

def _best_tp_by_price(symbol: str, orders: List[Dict[str, Any]]) -> Optional[str]:
    """
    Heuristic: בלי תג—מזהה TP1 כ-TP הקרוב ביותר בכיוון "רווחי".
    • אם צד ההזמנה SELL → מניחים לונג: הטייק הקרוב ביותר שמעל מחיר הסימן.
    • אם צד ההזמנה BUY  → מניחים שורט: הטייק הקרוב ביותר שמתחת למחיר הסימן.
    מחזיר clientOrderId של המועמד או None.
    """
    mark = _price_float(futures_mark_price(symbol))
    if not mark:
        # fallback קטן
        with suppress(Exception):
            from utils.binance_client import get_price
            mark = _price_float(get_price(symbol))
    if not mark: 
        return None

    # TP קנדידטים
    tps = [o for o in orders if _is_tp_order(o)]
    if not tps:
        return None

    best: Tuple[float, Dict[str, Any]] | None = None
    for o in tps:
        side = (o.get("side") or "").upper()
        # price יכול להיות None ב-TAKE_PROFIT_MARKET; נשתמש ב-stopPrice
        p = _price_float(o.get("price")) or _price_float(o.get("stopPrice"))
        if not p: 
            continue
        good = (side == "SELL" and p > mark) or (side == "BUY" and p < mark)
        if not good:
            continue
        dist = abs(p - mark)
        if (best is None) or (dist < best[0]):
            best = (dist, o)
    return str(best[1].get("clientOrderId")) if best else None

def health_tp1_for_symbol(symbol: str) -> Dict[str, Any]:
    lst = get_all_orders(symbol, limit=100) or []
    tags = _env_tags()
    tp_orders = [o for o in lst if _is_tp_order(o)]
    sl_orders = [o for o in lst if _is_sl_order(o)]

    has_tp = len(tp_orders) > 0
    has_tp1_tag = any(_has_tp1_tag(o, tags) for o in tp_orders)

    tp1_id: Optional[str] = None
    if has_tp1_tag:
        for o in tp_orders:
            if _has_tp1_tag(o, tags):
                tp1_id = str(o.get("clientOrderId") or "")
                break
    else:
        tp1_id = _best_tp_by_price(symbol, tp_orders)

    return {
        "has_tp": has_tp,
        "has_tp1_tag": has_tp1_tag,
        "tp_count": len(tp_orders),
        "sl_count": len(sl_orders),
        "tp1_clientOrderId": tp1_id,
    }

def live_orders_for_symbol(symbol: str) -> List[Dict[str, Any]]:
    """החזרה גולמית להצגה ב-UI (מטויבת)."""
    lst = get_all_orders(symbol, limit=100) or []
    keep = []
    for o in lst:
        st = (o.get("status") or "").upper()
        if st in ("NEW","PARTIALLY_FILLED"):
            keep.append({
                "orderId": o.get("orderId"),
                "clientOrderId": o.get("clientOrderId"),
                "type": o.get("type"),
                "side": o.get("side"),
                "positionSide": o.get("positionSide"),
                "status": o.get("status"),
                "price": o.get("price"),
                "stopPrice": o.get("stopPrice"),
                "origQty": o.get("origQty"),
                "executedQty": o.get("executedQty"),
                "updateTime": o.get("updateTime"),
            })
    return keep


