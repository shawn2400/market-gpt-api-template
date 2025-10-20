# manager/pos_publisher.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, asyncio, time
from typing import Any, Dict, List, Optional

from utils.redis_helper import set_json
from utils.binance_trade import get_client

_POS_PUB_ENABLE = os.getenv("POS_PUB_ENABLE", "1").lower() in ("1","true","yes","on")
_POS_PUB_INTERVAL_SEC = int(os.getenv("POS_PUB_INTERVAL_SEC", "20") or 20)
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
    stop = _flt(o.get("stopPrice", 0.0))
    if t in ("TAKE_PROFIT", "TAKE_PROFIT_MARKET"):
        return "TP"
    if t in ("STOP", "STOP_MARKET"):
        return "SL"
    # fallback: אם יש stopPrice + reduceOnly => STOP גנרי (לא מכריעים TP/SL לפי צד)
    if stop and ro:
        return "STOP"
    return "LIMIT"

def _collect_symbol_sync(cli, symbol: str) -> Dict[str, Any]:
    """
    איסוף נתוני פוזיציה/הזמנות לסימבול נתון (קריאות SDK סינכרוניות).
    רץ ב-thread executor כדי לא לחסום את event loop.
    """
    symbol = symbol.upper()
    pos_amt = 0.0
    entry_price = 0.0
    leverage = 0
    upnl = 0.0
    isolated = True
    mark_price = 0.0

    # פוזיציה
    try:
        pos_arr = cli.futures_position_information(symbol=symbol) or []
        pos = pos_arr[0] if isinstance(pos_arr, list) and pos_arr else {}
        pos_amt = _flt(pos.get("positionAmt", 0))
        entry_price = _flt(pos.get("entryPrice", 0))
        leverage = int(float(pos.get("leverage", 0) or 0))
        upnl = _flt(pos.get("unRealizedProfit", 0))
        isolated = str(pos.get("isolated", True)).lower() in ("true","1")
    except Exception:
        pass

    # mark price
    try:
        mp = cli.futures_mark_price(symbol=symbol) or {}
        mark_price = _flt(mp.get("markPrice", 0))
    except Exception:
        pass

    # הזמנות פתוחות
    orders: List[Dict[str, Any]] = []
    sl: List[Dict[str, Any]] = []
    tp: List[Dict[str, Any]] = []
    try:
        oo = cli.futures_get_open_orders(symbol=symbol) or []
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
    except Exception:
        pass

    has_pos = abs(pos_amt) > 0
    side = _side_from_amt(pos_amt)
    ts = int(time.time())

    # “תצוגה” ל-Trail/BE באופן נגזר (אין API ישיר)
    be = None
    trail = None
    if has_pos and entry_price and mark_price:
        be = {
            "entry": entry_price,
            "mark": mark_price,
            "dist_bps": round(((mark_price - entry_price) / entry_price) * 10000, 2)
        }
        if sl:
            # נבחר SL הקרוב למחיר ככלי חיווי trail-ish
            sl_sorted = sorted(
                [s for s in sl if s.get("stopPrice")],
                key=lambda x: abs(x["stopPrice"] - mark_price)
            )
            if sl_sorted:
                best = sl_sorted[0]
                trail = {
                    "stopPrice": best["stopPrice"],
                    "mark": mark_price,
                    "gap_bps": round((abs(mark_price - best["stopPrice"]) / max(1e-9, mark_price)) * 10000, 2),
                    "workingType": best.get("workingType","MARK_PRICE"),
                }

    return {
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

async def publish_positions_once() -> Dict[str, Any]:
    cli = get_client()
    loop = asyncio.get_event_loop()
    out: List[Dict[str, Any]] = []

    for sym in _WATCHLIST:
        try:
            doc = await loop.run_in_executor(None, _collect_symbol_sync, cli, sym)
            out.append(doc)
            # key פר-סימבול
            await set_json(f"pos:{sym}", doc, ttl_sec=max(_POS_PUB_INTERVAL_SEC * 3, 60))
        except Exception as e:
            await set_json(
                f"pos:{sym}",
                {"symbol": sym, "error": str(e), "ts": int(time.time())},
                ttl_sec=max(_POS_PUB_INTERVAL_SEC * 3, 60),
            )
        # השהייה קטנה להפחתת burst אל ה-API
        await asyncio.sleep(0.05)

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
    # “טקטיקת שקט”: אין ריצות מקבילות; הפעלה מחזורית רכה בלבד
    while True:
        try:
            await publish_positions_once()
        except Exception:
            # לא מפילים את הלולאה
            pass
        await asyncio.sleep(max(3, _POS_PUB_INTERVAL_SEC))

# לקריאה מ-main: start_pos_publisher(app)
def start_pos_publisher(app) -> None:
    if not _POS_PUB_ENABLE:
        return
    @app.on_event("startup")
    async def _startup():
        asyncio.create_task(_loop())

