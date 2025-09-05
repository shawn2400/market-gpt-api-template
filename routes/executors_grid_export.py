from __future__ import annotations
import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from utils.auth import require_api_key
from utils.export_utils import export_daily_csv, export_daily_pdf
from utils.pnl_summary import get_pnl_summary

logger = logging.getLogger("algogpt.export")

router = APIRouter(
    prefix="/export",
    tags=["Export"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/daily/csv", summary="Export daily trades to CSV")
async def export_csv(
    date: str = Query(None, description="תאריך בפורמט YYYY-MM-DD (ברירת מחדל היום)"),
    _: Any = Depends(require_api_key),
) -> Dict[str, Any]:
    try:
        path = export_daily_csv(date=date)
        return {"ok": True, "file": path}
    except Exception as e:
        logger.exception("[export] CSV error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily/pdf", summary="Export daily trades to PDF")
async def export_pdf(
    date: str = Query(None, description="תאריך בפורמט YYYY-MM-DD (ברירת מחדל היום)"),
    _: Any = Depends(require_api_key),
) -> Dict[str, Any]:
    try:
        path = export_daily_pdf(date=date)
        return {"ok": True, "file": path}
    except Exception as e:
        logger.exception("[export] PDF error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pnl", summary="PnL Summary")
async def pnl_summary(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    try:
        summary = get_pnl_summary()
        return {"ok": True, "summary": summary}
    except Exception as e:
        logger.exception("[export] PnL summary error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
