# routes/telegram_ping.py
from __future__ import annotations
from fastapi import APIRouter

router = APIRouter(prefix="/telegram", tags=["Telegram"])

@router.get("/ping", summary="Telegram ping")
async def ping():
    return {"ok": True}

