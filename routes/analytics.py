# routes/analytics.py
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class AnalyticsReport(BaseModel):
    report_url: str
    summary: str

@router.get("/pnl", response_model=AnalyticsReport)
async def pnl_report():
    """
    לא מחזיר base64 ענק, אלא קובץ PDF / PNG בסטטיק.
    """
    path = "/static/reports/pnl_today.pdf"
    summary = "PNL report for today available"
    return AnalyticsReport(report_url=path, summary=summary)









































