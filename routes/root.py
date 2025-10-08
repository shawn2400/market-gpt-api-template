# routes/root.py
from __future__ import annotations
from fastapi import APIRouter, Response

router = APIRouter(tags=["status"])

@router.get("/status", include_in_schema=False)
async def status_get():
    return {"ok": True, "service": "AlgoGPT", "path": "/status"}

@router.get("/ping", include_in_schema=False)
async def ping_get():
    return {"ok": True, "pong": True}

@router.head("/status", include_in_schema=False)
async def status_head():
    return Response(status_code=200)


