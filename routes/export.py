# routes/export.py
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from utils.auth import require_api_key
from utils.trade_storage import cleanup_static, load_trades

logger = logging.getLogger("algogpt.routes.export")

router = APIRouter(
    prefix="/export",
    tags=["Export"],
    dependencies=[Depends(require_api_key)],
)

# ────────────────────────────────────────────────
# Models
# ────────────────────────────────────────────────
class ExportResponse(BaseModel):
    ok: bool = True
    cleaned_files: int

class TradesResponse(BaseModel):
    ok: bool = True
    total: int
    items: list

# ────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────
@router.post("/cleanup", response_model=ExportResponse)
def cleanup(limit: int = Query(500, ge=50, le=2000)) -> ExportResponse:
    """מנקה קבצי cache ישנים בתיקיית static/cache"""
    try:
        cleanup_static(max_files=limit)
        return ExportResponse(cleaned_files=limit)
    except Exception as e:
        logger.exception("export_cleanup_failed")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/trades", response_model=TradesResponse)
def list_trades(limit: int = Query(100, ge=1, le=1000)) -> TradesResponse:
    """מחזיר את הטריידים האחרונים מה־cache"""
    try:
        trades = load_trades()
        if limit and len(trades) > limit:
            trades = trades[:limit]
        return TradesResponse(total=len(trades), items=trades)
    except Exception as e:
        logger.exception("export_trades_failed")
        raise HTTPException(status_code=500, detail=str(e))






