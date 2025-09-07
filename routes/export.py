# routes/export.py
from __future__ import annotations
import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from utils.auth import require_api_key

logger = logging.getLogger("algogpt.routes.export")

router = APIRouter(
    prefix="/export",
    tags=["Export"],
    dependencies=[Depends(require_api_key)],
)

@router.get("/status")
async def export_status() -> Dict[str, Any]:
    """
    מחזיר סטטוס בסיסי של מערכת ה־Export.
    """
    try:
        return {"ok": True, "status": "export-ready"}
    except Exception as e:
        logger.error("export_status failed: %s", e)
        raise HTTPException(500, f"export_status failed: {e}")









