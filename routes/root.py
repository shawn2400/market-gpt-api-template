# routes/root.py
from __future__ import annotations
from fastapi import APIRouter, Response

router = APIRouter(prefix="/meta", tags=["status"])

@router.get("/status", include_in_schema=False)
async def status_get():
    return {"ok": True, "service": "AlgoGPT", "path": "/meta/status"}

@router.get("/ping", include_in_schema=False)
async def ping_get():
    return {"ok": True, "pong": True, "path": "/meta/ping"}

@router.head("/status", include_in_schema=False)
async def status_head():
    return Response(status_code=200)


