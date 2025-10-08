from __future__ import annotations
from fastapi import APIRouter, Response

router = APIRouter(tags=["status"])

@router.get("/", include_in_schema=False)
async def root_get():
    return {"ok": True, "service": "algogpt", "root": "/"}

@router.head("/", include_in_schema=False)
async def root_head():
    return Response(status_code=200)
