# utils/health_tp1.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import time
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from contextlib import suppress

import httpx

# נשתמש ב־helpers אם קיימים; אחרת ניפול לפולבקים של python-binance בזמן ריצה
with suppress(Exception):
    from utils.binance_client import get_all_orders, futures_mark_price, get_price  # type: ignore

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
    coid = str((o.get("clientOrderId") or "")).upper()
    return any(t.upper() in coid for t in tags)

def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except Exception:
        return None

def _get_mark_price(symbol: str) -> Optional[float]:
    # 1) utils helper
    with suppress(Exception):
        p = futures_mark_price(symbol)
        pf = _f(p)
        if pf and pf > 0:
            return pf
    # 2) utils get_price (ספוט/פוטצ’רז—לא קריטי, רק קירוב)
    with suppress(Exception):
        p = get_price(symbol)  # type: ignore
        pf = _f(p)
        if pf and pf > 0:
            return pf
    # 3) Binance REST מהיר (ללא מפתח)
    with suppress(Exception):
        import httpx
        with httpx.Client(timeout=5.0) as cli:
            r = cli.get("https://fapi.binance.com/fapi/v1/ticker/price", params={"symbol": symbol.upper()})
            if r.status_code == 200:
                j = r.json()
                pf = _f(j.get("price"))
                if pf and pf > 0:
                    return pf
    return None

def _best_tp_by_price(symbol: str, orders: List[Dict[str, Any]]) -> Optional[str]:
    """
    בלי תג — מזהה TP1 כטייק הקרוב ביותר בכיוון הרווח:
      לונג → SELL שמעל המחיר; שורט → BUY שמתחת למחיר.
    """
    mark = _get_mark_price(symbol)
    if not mark:
        return None

    tps = [o for o in orders if _is_tp_order(o)]
    if not tps:
        return None

    best: Tuple[float, Dict[str, Any]] | None = None
    for o in tps:
        side = (o.get("side") or "").upper()
        p = _f(o.get("price")) or _f(o.get("stopPrice"))
        if not p:
            continue
        good = (side == "SELL" and p > mark) or (side == "BUY" and p < mark)
        if not good:
            continue
        dist = abs(p - mark)
        if (best is None) or (dist < best[0]):
            best = (dist, o)
    return str(best[1].get("clientOrderId")) if best else None

def _get_all_orders(symbol: str) -> List[Dict[str, Any]]:
    # אם יש helper — נשתמש בו
    with suppress(Exception):
        lst = get_all_orders(symbol, limit=100)  # type: ignore
        if isinstance(lst, list):
            return lst
    # פולבק מהיר ל־python-binance (רק אם יש מפתחות)
    with suppress(Exception):
        from binance.client import Client  # type: ignore
        api_key = os.getenv("BINANCE_API_KEY", "")
        api_sec = os.getenv("BINANCE_API_SECRET", "")
        if not api_key or not api_sec:
            return []
        cli = Client(api_key, api_sec)
        return cli.futures_get_open_orders(symbol=symbol.upper()) or []
    return []

def health_tp1_for_symbol(symbol: str) -> Dict[str, Any]:
    lst = _get_all_orders(symbol)
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
    }

def live_orders_for_symbol(symbol: str) -> List[Dict[str, Any]]:
    """להצגה ב-UI: רק הזמנות פעילות."""
    lst = _get_all_orders(symbol)
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

# ---------- Telegram helpers ----------
def _tg_info() -> Tuple[Optional[str], Optional[str]]:
    return (os.getenv("TELEGRAM_BOT_TOKEN") or None,
            os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID") or None)

async def _send_telegram_html(text: str) -> None:
    bot, chat = _tg_info()
    if not (bot and chat):
        return
    try:
        with httpx.Client(timeout=10.0) as cli:
            cli.post(f"https://api.telegram.org/bot{bot}/sendMessage",
                     json={"chat_id": int(chat) if str(chat).isdigit() else chat,
                           "text": text, "parse_mode": "HTML",
                           "disable_web_page_preview": True})
    except Exception:
        pass

# ---------- Async periodic checks ----------
async def quick_check_tp1(symbols: List[str],
                          tp1_tags: Optional[List[str]] = None,
                          notify_telegram: bool = False) -> Dict[str, Any]:
    tags = tp1_tags or _env_tags()
    out: Dict[str, Any] = {}
    lines: List[str] = [f"🩺 <b>TP1 Health</b> · tags=<code>{','.join(tags)}</code>"]

    for sym in symbols:
        s = sym.strip().upper()
        if not s:
            continue
        res = health_tp1_for_symbol(s)
        out[s] = res
        mark = "✅" if res.get("has_tp") else "⚠️"
        note = "TP1 tagged" if res.get("has_tp1_tag") else ("TP present" if res.get("has_tp") else "TP missing")
        lines.append(f"• {s}: {mark} <code>{note}</code> (TP={res.get('tp_count')}, SL={res.get('sl_count')})")

    if notify_telegram and len(lines) > 1:
        await _send_telegram_html("\n".join(lines))
    return out

async def health_check_tp1_tags(symbols: List[str], interval_sec: int = 600) -> None:
    """לולאה אסינכרונית—מריצה quick_check_tp1 כל interval_sec ושולחת לטלגרם."""
    sec = max(60, int(interval_sec))
    while True:
        try:
            await quick_check_tp1(symbols, tp1_tags=_env_tags(), notify_telegram=True)
        except Exception:
            pass
        await asyncio.sleep(sec)



