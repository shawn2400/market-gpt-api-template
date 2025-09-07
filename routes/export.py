# routes/export.py
from __future__ import annotations
import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends
from utils.auth import require_api_key

logger = logging.getLogger("algogpt.routes.export")

router = APIRouter(
    prefix="/export",
    tags=["Export"],
    dependencies=[Depends(require_api_key)],
)

@router.get("/status")
async def export_status() -> Dict[str, Any]:
    return {"ok": True, "status": "export-ready"}








