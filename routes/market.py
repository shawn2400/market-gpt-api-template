# routes/metrics.py
from __future__ import annotations
import time
from fastapi import APIRouter, Request
from utils.metrics import metrics_tracker

router = APIRouter(
    prefix="/metrics",
    tags=["Metrics"]
)

@router.get("/", summary="System metrics snapshot")
async def get_metrics(request: Request):
    """
    מחזיר snapshot של המטריקות הפנימיות:
    - uptime
    - ספירת בקשות/שגיאות
    - סטטיסטיקות זמני תגובה
    - RPS
    """
    return {
        "ok": True,
        "ts": int(time.time()),
        "client": request.client.host if request.client else None,
        "metrics": metrics_tracker.get_metrics(),
    }

























