# routes/kpi_mini.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Dict, Any
import os
from contextlib import suppress

router = APIRouter()

try:
    from utils.metrics_tracker import get_metrics_snapshot  # type: ignore
except Exception:
    def get_metrics_snapshot() -> Dict[str, Any]:  # type: ignore
        return {"ok": False, "error": "metrics_unavailable"}

@router.get("/ops/mini", tags=["ops-ui"])
async def mini_dashboard():
    snap = get_metrics_snapshot()
    # 12 KPI בסיסיים + quick-hints
    k = {
        "Hit-rate": os.getenv("KPI_HIT_RATE", "—"),   # אם לא קיים חישוב – נשאיר אופציונלי
        "Avg R": os.getenv("KPI_AVG_R", "—"),
        "TP merge%": os.getenv("KPI_TP_MERGE_PCT", "—"),
        "Missed-fill%": os.getenv("KPI_MISSED_FILL_PCT", "—"),
        "Slip p50": os.getenv("KPI_SLIP_P50", "—"),
        "Slip p95": os.getenv("KPI_SLIP_P95", "—"),
        "Time-to-TP1 p50": os.getenv("KPI_TTTP1_P50", "—"),
        "Time-to-TP1 p95": os.getenv("KPI_TTTP1_P95", "—"),
        "Open approvals": os.getenv("KPI_APPROVALS_OPEN", "—"),
        "Scan passed": snap.get("scan_passed"),
        "Scan blocked": snap.get("scan_blocked"),
        "Approvals created": snap.get("approvals_created"),
    }

    def row(a,b): return f"<tr><th style='text-align:left;padding:.4rem .6rem;background:#fafafa'>{a}</th><td style='padding:.4rem .6rem'>{b}</td></tr>"
    rows = "\n".join([row(k_, k[k_]) for k_ in k])

    body = (
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:Inter,system-ui,Segoe UI,Arial;max-width:880px;margin:2rem auto;line-height:1.5'>"
        "<h2 style='margin:0 0 1rem 0'>Mini Console · KPIs</h2>"
        "<table style='border-collapse:collapse;width:100%;border:1px solid #eee'>"
        f"{rows}"
        "</table>"
        "<p style='color:#777;margin-top:1rem'>טיפ: אפשר להרחיב את ה־KPIs ע״י הזנת ENV/עיבוד אנליטי קל בדיעבד.</p>"
        "</body>"
    )
    return HTMLResponse(body)

@router.get("/ops/mini.json", tags=["ops-ui"])
async def mini_json():
    snap = get_metrics_snapshot()
    return JSONResponse({"ok": True, "snapshot": snap})
