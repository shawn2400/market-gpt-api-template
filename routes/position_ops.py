# routes/position_ops.py
from __future__ import annotations
from fastapi import APIRouter, Query, HTTPException
from typing import Dict, Any, Optional
import os, time, logging

logger = logging.getLogger("algogpt.position_ops")
router = APIRouter(tags=["position-ops"])

# Fallback נמוך-חיכוך ל-Binance אם אין פונקציה יעודית ב-trade_executor
def _fallback_reduce_market(symbol: str, side: str, qty: float) -> Dict[str, Any]:
    try:
        from binance.client import Client  # type: ignore
        k = os.getenv("BINANCE_API_KEY","").strip()
        s = os.getenv("BINANCE_API_SECRET","").strip()
        if not k or not s:
            return {"ok": False, "error": "binance_keys_missing"}
        c = Client(k, s)
        # אם LONG פתוח – כדי לסגור חלקית נפתח הזמנה הפוכה reduceOnly
        inv_side = "SELL" if side.upper() == "BUY" else "BUY"
        order = c.futures_create_order(
            symbol=symbol.upper(),
            side=inv_side,
            type="MARKET",
            quantity=float(qty),
            reduceOnly=True,
            newClientOrderId=f"ALG_POSOP_{symbol}_{inv_side}_{int(time.time())}"
        )
        return {"ok": True, "exchange":"binance_futures", "order": order}
    except Exception as e:
        logger.error("fallback_reduce_market failed: %s", e)
        return {"ok": False, "error": "fallback_reduce_failed", "detail": str(e)}

def _exec_close_partial(symbol: str, side: str, part: float) -> Dict[str, Any]:
    part = float(part)
    if not (0 < part <= 1.0):
        return {"ok": False, "error":"bad_part_ratio"}
    # נסה דרך trade_executor אם קיים
    try:
        from utils.trade_executor import close_position_partial  # type: ignore
        return {"ok": True, "result": close_position_partial(symbol.upper(), side.upper(), part)}
    except Exception:
        pass
    # אחרת fallback: צריך כמות בפועל – אם אין לנו, נניח שהלקוח מעביר qty.
    return {"ok": False, "error": "no_executor_partial", "hint": "supply qty via /close_qty endpoint"}

@router.post("/ops/position/close_half")
async def close_half(symbol: str = Query(...), side: str = Query(..., regex="^(?i)(BUY|SELL|LONG|SHORT)$")):
    """
    סוגר חצי פוזיציה (by ratio) – אם יש פונקציה ייעודית, נשתמש בה; אחרת יוחזר hint.
    """
    res = _exec_close_partial(symbol, side, 0.5)
    if not res.get("ok"):
        # fallback דורש qty – אין לנו, נחזיר מידע
        return {"ok": False, "error":"partial_close_needs_qty", "use": f"/ops/position/close_qty?symbol={symbol}&side={side}&qty=<number>"}
    return res

@router.post("/ops/position/close_qty")
async def close_qty(symbol: str = Query(...), side: str = Query(..., regex="^(?i)(BUY|SELL|LONG|SHORT)$"), qty: float = Query(..., gt=0)):
    """
    סוגר כמות נתונה מהפוזיציה ע"י reduceOnly MARKET הפוך (fallback בטוח).
    """
    return _fallback_reduce_market(symbol, side, qty)

@router.post("/ops/position/close_all")
async def close_all(symbol: str = Query(...), side: str = Query(..., regex="^(?i)(BUY|SELL|LONG|SHORT)$"), qty: Optional[float] = Query(None, gt=0)):
    """
    סוגר את כל הפוזיציה. אם הלקוח לא מעביר qty – ננסה להסתמך על trade_executor; אחרת fallback.
    """
    try:
        from utils.trade_executor import close_position_all  # type: ignore
        return {"ok": True, "result": close_position_all(symbol.upper(), side.upper())}
    except Exception:
        if qty and qty > 0:
            return _fallback_reduce_market(symbol, side, qty)
        return {"ok": False, "error":"missing_qty_for_fallback", "hint":"pass qty to close_all or install trade_executor.close_position_all"}

@router.post("/ops/position/reverse")
async def reverse(symbol: str = Query(...), side: str = Query(..., regex="^(?i)(BUY|SELL|LONG|SHORT)$"), qty: float = Query(..., gt=0), leverage: int = Query(0, ge=0)):
    """
    היפוך פוזיציה: סוגר (reduceOnly) את הקיימת ופותח הפוכה לאותה כמות (או יותר).
    """
    inv = "SELL" if side.upper() in ("BUY","LONG") else "BUY"
    # 1) סגור את הישנה (reduceOnly)
    a = _fallback_reduce_market(symbol, side, qty)
    if not a.get("ok"):
        return {"ok": False, "stage":"reduce", "detail": a}
    # 2) פתח הפוכה
    try:
        from utils.trade_executor import place_futures_market  # type: ignore
        payload = {"symbol":symbol.upper(),"side":inv,"qty":qty,"leverage":(leverage or 0) or 1,"position_side":"BOTH","note":"[mode: MARKET] REVERSE"}
        b = await place_futures_market(payload)  # type: ignore
        return {"ok": bool(b.get("ok")), "reduce": a, "open": b}
    except Exception:
        # fallback גולמי
        try:
            from binance.client import Client  # type: ignore
            k = os.getenv("BINANCE_API_KEY","").strip()
            s = os.getenv("BINANCE_API_SECRET","").strip()
            c = Client(k, s)
            if leverage and leverage > 0:
                try: c.futures_change_leverage(symbol=symbol.upper(), leverage=int(leverage))
                except Exception: pass
            order = c.futures_create_order(symbol=symbol.upper(), side=inv, type="MARKET", quantity=float(qty),
                                           newClientOrderId=f"ALG_REV_{symbol}_{inv}_{int(time.time())}")
            return {"ok": True, "reduce": a, "open": {"order":order, "exchange":"binance_futures"}}
        except Exception as e:
            return {"ok": False, "stage":"reverse_open_failed", "error": str(e)}
