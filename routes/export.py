# routes/export.py
from __future__ import annotations
import logging
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from utils.auth import require_api_key
from utils.trade_storage import cleanup_static

logger = logging.getLogger("algogpt.routes.export")

router = APIRouter(
    prefix="/export",
    tags=["Export"],
    dependencies=[Depends(require_api_key)],
)

class ExportResponse(BaseModel):
    ok: bool = True
    cleaned_files: int

@router.post("/cleanup", response_model=ExportResponse)
def cleanup(limit: int = Query(500, ge=50, le=2000)) -> ExportResponse:
    """מנקה קבצי cache ישנים בתיקיית static/cache"""
    try:
        cleanup_static(max_files=limit)
        return ExportResponse(cleaned_files=limit)
    except Exception as e:
        logger.exception("export_cleanup_failed")
        raise HTTPException(status_code=500, detail=str(e))



