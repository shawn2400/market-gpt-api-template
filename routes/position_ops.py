# routes/position_ops.py
from __future__ import annotations
from typing import Dict, Any, Optional
from fastapi import APIRouter, Body, HTTPException

import os, logging
logger = logging.getLogger("algogpt.position_ops")

router = APIRouter(tags=["position-ops"])

# ננסה לייבא את המימוש הראשי
_execute_live = None
_close_reduce  = None

try:
    from utils.trade_executor import execute_trade_live  # type: ignore
    _execute_live = execute_trade_live
except Exception:
    pass

async def _close_position(symbol: str, side: str, fraction: float, leverage: Optional[int] = None) -> Dict[str, Any]:
    """
    סוגר חלק/הכל ע"י הזמנת עסקה הפוכה reduce_only.
    fraction: 0..1 (1 = הכל)
    """
    if not _execute_live:
        raise HTTPException(status_code=500, detail="execute_trade_live missing")

    side_rev = "SELL" if side.upper() == "BUY" else "BUY"

    try:
        res = await _execute_live(
            symbol=symbol,
            side=side_rev,
            budget=None,
            leverage=leverage or 0,
            dry_run=False,
            quantity=None,           # הכמות תיקבע מתוך fraction בפונקציה אם נתמכת, אחרת יתבצע best effort
            entry=None,
            tp_targets=None,
            sl_targets=None,
            tp_splits=None,
            sl_splits=None,
            confirm_first=False,
            telegram_chat_id=int(os.getenv("TELEGRAM_CHAT_ID") or 0),
            position_side="BOTH",
            reduce_only=True,
            fraction=fraction,       # הרבה מממשים תומכים בפרמטר כזה; אם לא, יתעלמו
        )
        return res
    except Exception as e:
        logger.exception("close_position failed")
        return {"ok": False, "error": "close_failed", "detail": str(e)}

@router.post("/ops/close_half", summary="Close half of a position (reduce-only)")
async def close_half(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    side   = (payload.get("side") or "").upper()
    lev    = payload.get("leverage")
    if not (symbol and side in ("BUY","SELL")):
        raise HTTPException(status_code=422, detail="symbol/side required")
    res = await _close_position(symbol, side, fraction=0.5, leverage=lev)
    return {"ok": bool(res.get("ok")), "result": res}

@router.post("/ops/close_all", summary="Close entire position (reduce-only)")
async def close_all(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    side   = (payload.get("side") or "").upper()
    lev    = payload.get("leverage")
    if not (symbol and side in ("BUY","SELL")):
        raise HTTPException(status_code=422, detail="symbol/side required")
    res = await _close_position(symbol, side, fraction=1.0, leverage=lev)
    return {"ok": bool(res.get("ok")), "result": res}

@router.post("/ops/reverse", summary="Reverse position (close current and open opposite)")
async def reverse(payload: Dict[str, Any] = Body(...)):
    """
    reverse – סוגר הכל ואח"כ פותח כיוון הפוך בכמות מצוינת.
    payload: {symbol, side, leverage, quantity}
    side כאן הוא הצד הנוכחי; נפתח את ההפוך.
    """
    symbol = (payload.get("symbol") or "").upper()
    side   = (payload.get("side") or "").upper()
    lev    = int(payload.get("leverage") or 0)
    qty    = float(payload.get("quantity") or payload.get("qty") or 0)
    if not (symbol and side in ("BUY","SELL") and qty > 0):
        raise HTTPException(status_code=422, detail="symbol/side/quantity required")

    # 1) סגירה מלאה
    close_res = await _close_position(symbol, side, fraction=1.0, leverage=lev)
    if not bool(close_res.get("ok")):
        return {"ok": False, "step": "close", "result": close_res}

    # 2) פתיחה הפוכה
    if not _execute_live:
        raise HTTPException(status_code=500, detail="execute_trade_live missing")
    side_rev = "SELL" if side == "BUY" else "BUY"

    try:
        open_res = await _execute_live(
            symbol=symbol,
            side=side_rev,
            budget=None,
            leverage=lev,
            dry_run=False,
            quantity=qty,
            entry=None,
            tp_targets=None,
            sl_targets=None,
            tp_splits=None,
            sl_splits=None,
            confirm_first=False,
            telegram_chat_id=int(os.getenv("TELEGRAM_CHAT_ID") or 0),
            position_side="BOTH",
            reduce_only=False,
        )
        return {"ok": bool(open_res.get("ok")), "close": close_res, "open": open_res}
    except Exception as e:
        return {"ok": False, "step": "open", "error": str(e), "close": close_res}

