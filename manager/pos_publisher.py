# manager/pos_publisher.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, asyncio, time, math
from typing import Any, Dict, List, Tuple, Optional

from utils.redis_helper import set_json
from utils.binance_trade import get_client

_POS_PUB_ENABLE = os.getenv("POS_PUB_ENABLE", "1").lower() in ("1","true","yes","on")
_POS_PUB_INTERVAL_SEC = int(os.getenv("POS_PUB_INTERVAL_SEC", "20"))
_WATCHLIST = [s.strip().upper() for s in (os.getenv("WATCHLIST","BTCUSDT,ETHUSDT").split(",")) if s.strip()]

def _flt(x: Any, d: int = 8) -> float:
    try:
        return round(float(x), d)
    except Exception:
        return 0.0

def _side_from_amt(amt: float) -> Optional[str]:
    if amt > 0: return "BUY"
    if amt < 0: return "SELL"
    return None

def _classify_order(o: Dict[str, Any]) -> str:
    """
    מנסה לזהות TP/SL/Trail לפי סוג/תנאי/מילות מפתח.
    """
    t = str(o.get("type","")).upper()
    ro = bool(o.get("reduceOnly", False))
    w = str(o.get("workingType","MARK_PRICE")).upper()
    stop = _flt(o.get("stopPrice", 0.0))
    if t in ("TAKE_PROFIT", "TAKE_PROFIT_MARKET"):
        return "TP"
    if t in ("STOP", "STOP_MARKET"):
        return "SL"
    # fallback: אם יש stopPrice + reduceOnly => SL/TP תלוי בצד
    if stop and ro:
        # BUY reduceOnly + stop -> TP לשורט או SL ללונג; לא נכנסים לעומק, מציגים "STOP"
        return "STOP"
    # הזמנות LIMIT רגילות
    return "LIMIT"

async def _collect_symbol(cli, symbol: str) -> Dict[str, Any]:
    symbol = symbol.upper()
    pos_arr = cli.futures_position_information(symbol=symbol)  # list len=1
    pos = pos_arr[0] if isinstance(pos_arr, list) and pos_arr else {}

    # כמויות ומחירים
    pos_amt = _flt(pos.get("positionAmt", 0))
    entry_price = _flt(pos.get("entryPrice", 0))
    leverage = int(float(pos.get("leverage", 0) or 0))
    upnl = _flt(pos.get("unRealizedProfit", 0))
    isolated = str(pos.get("isolated", True)).lower() in ("true","1")

    # mark price
    try:
        mp = cli.futures_mark_price(symbol=symbol)
        mark_price = _flt(mp.get("markPrice", 0))
    except Exception:
        mark_price = 0.0

    # הזמנות פתוחות
    oo = cli.futures_get_open_orders(symbol=symbol) or []
    orders: List[Dict[str, Any]] = []
    sl: List[Dict[str, Any]] = []
    tp: List[Dict[str, Any]] = []

    for o in oo:
        kind = _classify_order(o)
        entry = {
            "orderId": o.get("orderId"),
            "type": o.get("type"),
            "status": o.get("status"),
            "side": o.get("side"),
            "reduceOnly": bool(o.get("reduceOnly", False)),
            "qty": _flt(o.get("origQty", o.get("origQuantity", 0))),
            "price": _flt(o.get("price", 0)),
            "stopPrice": _flt(o.get("stopPrice", 0)),
            "workingType": o.get("workingType", "MARK_PRICE"),
            "class": kind,
        }
        orders.append(entry)
        if kind == "SL": sl.append(entry)
        if kind == "TP": tp.append(entry)

    has_pos = abs(pos_amt) > 0
    side = _side_from_amt(pos_amt)
    ts = int(time.time())

    # Trail/BE “תצוגה” — נגזרות (אין API ישיר). מציגים רק כשיש פוזיציה:
    be = None
    trail = None
    if has_pos and entry_price and mark_price:
        # מרחק לנקודת BE (משוער): אין עמלות/מימון — תצוגה בלבד.
        be = {
            "entry": entry_price,
            "mark": mark_price,
            "dist_bps": round( ( (mark_price - entry_price)/entry_price * 10000 ), 2 )
        }
        # trail dummy: אם יש SL מסוג STOP_MARKET ונע קרוב לשוק => נתייג "trail-ish"
        if sl:
            # נבחר SL עם stopPrice הקרוב ביותר למחיר
            sl_sorted = sorted([s for s in sl if s.get("stopPrice")], key=lambda x: abs(x["stopPrice"] - mark_price))
            if sl_sorted:
                best = sl_sorted[0]
                trail = {
                    "stopPrice": best["stopPrice"],
                    "mark": mark_price,
                    "gap_bps": round( (abs(mark_price - best["stopPrice"])/mark_price * 10000), 2 ),
                    "workingType": best.get("workingType","MARK_PRICE"),
                }

    doc = {
        "symbol": symbol,
        "has_position": has_pos,
        "side": side,
        "amt": pos_amt,
        "entry": entry_price,
        "mark": mark_price,
        "lev": leverage,
        "isolated": isolated,
        "uPnL": upnl,
        "orders": orders,
        "tp": tp,
        "sl": sl,
        "be": be,
        "trail": trail,
        "ts": ts,
    }
    return doc

async def publish_positions_once() -> Dict[str, Any]:
    cli = get_client()
    out: List[Dict[str, Any]] = []
    for sym in _WATCHLIST:
        try:
            doc = await asyncio.get_event_loop().run_in_executor(None, _collect_symbol, cli, sym)
            out.append(doc)
            # key פר-סימבול
            await set_json(f"pos:{sym}", doc, ttl_sec=max(_POS_PUB_INTERVAL_SEC * 3, 60))
        except Exception as e:
            # כתיבה “ריקה” כדי שה-UI ידע שאין נתונים
            await set_json(f"pos:{sym}", {"symbol": sym, "error": str(e), "ts": int(time.time())}, ttl_sec=max(_POS_PUB_INTERVAL_SEC * 3, 60))
    # סיכום כללי
    summary = {
        "items": out,
        "active": [d for d in out if d.get("has_position")],
        "ts": int(time.time()),
    }
    await set_json("pos:all", summary, ttl_sec=max(_POS_PUB_INTERVAL_SEC * 3, 60))
    return {"ok": True, "count": len(out)}

async def _loop():
    if not _POS_PUB_ENABLE:
        return
    while True:
        try:
            await publish_positions_once()
        except Exception:
            pass
        await asyncio.sleep(max(3, _POS_PUB_INTERVAL_SEC))

# לקריאה מ-main: start_pos_publisher(app)
def start_pos_publisher(app) -> None:
    if not _POS_PUB_ENABLE:
        return
    @app.on_event("startup")
    async def _startup():
        asyncio.create_task(_loop())
