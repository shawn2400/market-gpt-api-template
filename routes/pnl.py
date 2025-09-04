# routes/pnl.py
from __future__ import annotations
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from utils.auth import require_api_key
from utils.pnl_tracker import update_pnl, generate_pnl_pdf, _load_json_or_empty

router = APIRouter(
    prefix="/pnl",
    tags=["PnL"],
    dependencies=[Depends(require_api_key)],
)

def _try_get_summary() -> Dict[str, Any]:
    # אם יש utils.pnl_summary – נעדיף אותו; אחרת fallback ל־pnl_tracker.json
    try:
        from utils.pnl_summary import get_pnl_summary  # type: ignore
        summary = get_pnl_summary(limit_days=30)  # חתך סביר
        return {"ok": True, "summary": summary, "source": "pnl_summary"}
    except Exception:
        data = _load_json_or_empty("pnl_tracker.json")
        return {"ok": True, "summary": data, "source": "pnl_tracker"}

@router.get("/summary")
def get_pnl_summary_alias() -> Dict[str, Any]:
    """
    אליאס שנדרש ע"י הקונקטור: /pnl/summary
    """
    try:
        # נוודא עדכון דלתא לפני סיכום (לא חובה, אבל עדיף)
        try:
            update_pnl()
        except Exception:
            pass
        return _try_get_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"get_pnl_summary failed: {e}")

@router.get("/daily")
def get_daily_pnl() -> Dict[str, Any]:
    """
    סיכום יומי מתוך pnl_tracker.json (קיים במערכת)
    """
    try:
        data = _load_json_or_empty("pnl_tracker.json")
        return {"ok": True, "data": data, "source": "pnl_tracker"}
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






