# routes/analytics.py
from __future__ import annotations
from fastapi import APIRouter
router = APIRouter(prefix="/analytics", tags=["Analytics"])  # בלי Depends

@router.get("/macro", operation_id="getMacro")
async def get_macro():
    try:
        from utils.macro import snapshot  # אם קיים אצלך
        data = snapshot()
        return {"ok": True, **(data or {})}
    except Exception:
        # לא נכשלים ב-401; מחזירים 200 עם ok=False כדי לשמור ציבורי
        return {"ok": False, "note": "macro provider not configured"}


