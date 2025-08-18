# routes/analytics.py
from __future__ import annotations
from fastapi import APIRouter

router = APIRouter(prefix="/analytics", tags=["Analytics"])  # ללא Depends/Bearer

@router.get("/macro", operation_id="getMacro")
async def get_macro():
    try:
        # from utils.macro import snapshot
        # data = snapshot() or {}
        # return {"ok": True, **data}
        return {"ok": False, "note": "macro provider not configured"}
    except Exception:
        return {"ok": False, "note": "macro error"}




