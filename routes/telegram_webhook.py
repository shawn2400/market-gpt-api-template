# -*- coding: utf-8 -*-
from __future__ import annotations

# Placeholder Telegram webhook route. The full approve/reject + execution flow will be added in the PR diff.

from fastapi import APIRouter

router = APIRouter(prefix="/telegram", tags=["telegram"])

@router.get("/ping")
async def ping():
    return {"ok": True}
