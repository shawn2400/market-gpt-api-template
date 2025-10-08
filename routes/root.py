from __future__ import annotations
from fastapi import APIRouter, Response

router = APIRouter(tags=["status"])

@router.get("/", include_in_schema=False)
async def root_get():
    """
    Simple alive endpoint for platform root checks.
    Returns 200 and a tiny JSON so GET / works.
    """
    return {"ok": True, "service": "algogpt", "root": "/"}

@router.head("/", include_in_schema=False)
async def root_head():
    """
    Render.com and לודים אחרים עושים HEAD / לזיהוי שירות חי.
    נחזיר 200 בלי גוף כדי לא לקבל 405.
    """
    return Response(status_code=200)
