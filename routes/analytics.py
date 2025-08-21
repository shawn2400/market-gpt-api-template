# routes/analytics.py
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import List
from datetime import datetime

router = APIRouter(tags=["Analytics"])


class AnalyticsReport(BaseModel):
    report_url: str
    summary: str
    created_at: str


class AnalyticsListResponse(BaseModel):
    ok: bool = True
    count_total: int
    reports: List[AnalyticsReport] = Field(default_factory=list)


@router.get("/pnl", response_model=AnalyticsListResponse)
async def pnl_report():
    """
    מחזיר רשימת דוחות PNL כקבצים בסטטיק.
    לא שולח Base64 כבד בתוך JSON.
    """
    reports: List[AnalyticsReport] = []

    # 🔹 דוגמה: דו"ח יומי ב-PDF
    reports.append(AnalyticsReport(
        report_url="/static/reports/pnl_today.pdf",
        summary="PNL report for today",
        created_at=datetime.utcnow().isoformat()
    ))

    # 🔹 אפשר להוסיף כאן עוד דוחות (אתמול, שבועי, חודשי)
    # reports.append(...)

    return AnalyticsListResponse(
        count_total=len(reports),
        reports=reports
    )










































