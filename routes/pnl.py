# routes/pnl.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from typing import Dict, Any
from utils.auth import require_api_key
from utils.pnl_tracker import update_pnl, generate_pnl_pdf, _load_json_or_empty

router = APIRouter(
    prefix="/pnl",
    tags=["PnL"],
    dependencies=[Depends(require_api_key)],
)

@router.get("/daily")
def get_daily_pnl() -> Dict[str, Any]:
    """
    מחזיר סיכום PnL יומי מתוך pnl_tracker.json
    """
    try:
        data = _load_json_or_empty("pnl_tracker.json")
        return {"ok": True, "date": list(data.keys())[-1] if data else None, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"get_daily_pnl failed: {e}")

@router.get("/export-pdf")
def export_pnl_pdf():
    """
    מפיק PDF של דוח PnL ושולח אותו.
    """
    try:
        path = generate_pnl_pdf(limit_days=7)
        if not path:
            raise ValueError("No PnL data to export")
        return FileResponse(path, media_type="application/pdf", filename="pnl_report.pdf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"export_pnl_pdf failed: {e}")





