# utils/health_tp1.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from contextlib import suppress

from utils.binance_client import get_all_orders, futures_mark_price, get_price

TP_STATUSES = {"NEW", "PARTIALLY_FILLED"}
TP_TYPES = {"TAKE_PROFIT", "TAKE_PROFIT_MARKET", "TAKE_PROFIT_LIMIT"}
SL_TYPES = {"STOP", "STOP_MARKET", "STOP_LOSS_LIMIT"}

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
    return any(t for t in tags if t and t in coid)

def _price_float(v: Any) -> Optional[float]:
    with suppress(Exception):
        if v is None:
            return None
        return float(v)
    return None

def _best_tp_by_price(symbol: str, orders: List[Dict[str, Any]]) -> Optional[str]:
    """
    Heuristic: בלי תג—מזהה TP1 כ-TP הקרוב ביותר בכיוון “רווחי”.
    • אם side=SELL → כנראה לונג: טייק הקרוב ביותר שמעל מחיר הסימן.
    • אם side=BUY  → כנראה שורט: טייק הקרוב ביותר שמתחת למחיר הסימן.
    """
    mark = _price_float(futures_mark_price(symbol))
    if not mark:
        mark = _price_float(get_price(symbol))
    if not mark:
        return None

    tps = [o for o in orders if _is_tp_order(o)]
    if not tps:
        return None

    best: Tuple[float, Dict[str, Any]] | None = None
    for o in tps:
        side = (o.get("side") or "").upper()
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
        "symbol": symbol.upper(),
        "has_tp": has_tp,
        "has_tp1_tag": has_tp1_tag,
        "tp_count": len(tp_orders),
        "sl_count": len(sl_orders),
        "tp1_clientOrderId": tp1_id,
        "open_conditional": [
            {
                "orderId": o.get("orderId"),
                "clientOrderId": o.get("clientOrderId"),
                "type": o.get("type"),
                "side": o.get("side"),
                "positionSide": o.get("positionSide","BOTH"),
                "status": o.get("status"),
                "price": o.get("price"),
                "stopPrice": o.get("stopPrice"),
                "origQty": o.get("origQty"),
                "executedQty": o.get("executedQty"),
                "updateTime": o.get("updateTime"),
            }
            for o in tp_orders + sl_orders
            if (o.get("status") or "").upper() in TP_STATUSES
        ],
    }

def live_orders_for_symbol(symbol: str) -> List[Dict[str, Any]]:
    """Raw (but trimmed) live orders for UI."""
    lst = get_all_orders(symbol, limit=100) or []
    keep = []
    for o in lst:
        st = (o.get("status") or "").upper()
        if st in ("NEW", "PARTIALLY_FILLED"):
            keep.append({
                "orderId": o.get("orderId"),
                "clientOrderId": o.get("clientOrderId"),
                "type": o.get("type"),
                "side": o.get("side"),
                "positionSide": o.get("positionSide", "BOTH"),
                "status": o.get("status"),
                "price": o.get("price"),
                "stopPrice": o.get("stopPrice"),
                "origQty": o.get("origQty"),
                "executedQty": o.get("executedQty"),
                "updateTime": o.get("updateTime"),
            })
    return keep

# -------- Telegram notify helpers --------
async def _send_telegram_html(text: str) -> None:
    bot = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID")
    if not bot or not chat:
        return
    url = f"https://api.telegram.org/bot{bot}/sendMessage"
    payload = {"chat_id": int(chat) if str(chat).isdigit() else chat,
               "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    with suppress(Exception):
        import httpx
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0)) as cli:
            await cli.post(url, json=payload)

# -------- Periodic checks --------
async def quick_check_tp1(symbols: List[str], tp1_tags: Optional[str] = None, notify_telegram: bool = False):
    tags = [t.strip() for t in str(tp1_tags or os.getenv("TP1_TAGS", "TP1,tp1,tp_1,TAKE_PROFIT_1")).split(",") if t.strip()]
    out: Dict[str, Any] = {}
    lines: List[str] = ["🩺 <b>TP1 Health</b>"]

    for sym in symbols:
        symu = str(sym).upper().strip()
        res = health_tp1_for_symbol(symu)
        out[symu] = res
        mark = "✅" if (res.get("has_tp") and (res.get("has_tp1_tag") or res.get("tp1_clientOrderId"))) else "⚠️"
        extra = ""
        if not res.get("has_tp"):
            extra = " (no TP orders)"
        elif not res.get("has_tp1_tag") and not res.get("tp1_clientOrderId"):
            extra = " (no TP1)"
        lines.append(f"• {symu}: {mark}{extra}")

    if notify_telegram and len(lines) > 1:
        await _send_telegram_html("\n".join(lines))
    return out

async def health_check_tp1_tags(symbols: List[str], interval_sec: int = 600):
    interval_sec = max(60, int(interval_sec))
    while True:
        try:
            await quick_check_tp1(symbols, tp1_tags=os.getenv("TP1_TAGS"), notify_telegram=True)
        except Exception as e:
            with suppress(Exception):
                await _send_telegram_html(f"⚠️ <b>TP1 watcher error</b>\n<code>{e}</code>")
        await asyncio.sleep(interval_sec)



