# routes/metrics.py
from __future__ import annotations
from fastapi import APIRouter
from utils.metrics import metrics_tracker

# לא /metrics (כבר ממופה ב-main.py ל-Prometheus). כאן JSON קל לעבודה.
router = APIRouter(tags=["Metrics"])

@router.get("/metrics-json")
def metrics_json():
    return metrics_tracker.get_metrics()

