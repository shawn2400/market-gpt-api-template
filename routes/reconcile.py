# routes/reconcile.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from typing import Any, Dict

router = APIRouter(prefix="/reconcile", tags=["Reconcile"])

@router.post("/all")
async def reconcile_all() -> Dict[str, Any]:
    """
    Recon עדין אחרי ריסטארט: מסנכרן גריד/SL/TP לכל הסימבולים עם פוזיציות פתוחות,
    ומנקה סטייט יתום (ללא פוזיציה) אם עבר ה-TTL.
    """
    try:
        from utils.reconcile import reconcile_after_restart
        res = await reconcile_after_restart(sleep_first=0.0)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{symbol}")
async def reconcile_symbol(symbol: str) -> Dict[str, Any]:
    """
    Recon נקודתי לסימבול בודד (ensure grid או שחזור TP/SL אם חסר).
    """
    try:
        from utils.reconcile import reconcile_symbol as _rec_sym
        res = await _rec_sym(symbol.upper())
        return {"ok": True, **res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

