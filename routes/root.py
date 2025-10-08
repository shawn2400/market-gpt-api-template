# routes/root.py
from __future__ import annotations

from fastapi import APIRouter, Response

router = APIRouter(tags=["status"])

@router.get("/", include_in_schema=False)
async def root_get():
    """
    נקודת שורש פשוטה לבדיקה שהשירות חי.
    מחזירה 200 ו־JSON קטן כדי ש־GET / יעבוד.
    """
    return {"ok": True, "service": "AlgoGPT", "root": "/"}

@router.head("/", include_in_schema=False)
async def root_head():
    """
    חלק מהפלפורמות (למשל Render) עושות HEAD / כדי לבדוק חיות.
    נחזיר 200 ללא גוף כדי למנוע 405.
    """
    return Response(status_code=200)

