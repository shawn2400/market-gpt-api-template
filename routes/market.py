# routes/metrics.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from typing import Dict, Any
import time

from utils.auth import require_api_key
from utils.metrics import metrics_tracker

router = APIRouter(
    prefix="/metrics",
    tags=["Metrics"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/", summary="Core metrics snapshot")
async def get_metrics() -> Dict[str, Any]:
    """
    החזרת מצב המערכת:
    - uptime
    - counters (total/errors/by_status)
    - latencies (avg/min/max/p50/p95)
    - RPS (5s/60s)
    """
    return metrics_tracker.get_metrics()

@router.get("/ping")
async def ping_metrics() -> Dict[str, Any]:
    return {"ok": True, "ts": int(time.time())}

# --- Middleware hook ---
@router.middleware("http")
async def track_requests(request: Request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
    except Exception as e:
        duration_ms = (time.time() - start) * 1000.0
        metrics_tracker.observe_request(500, duration_ms)
        raise
    else:
        duration_ms = (time.time() - start) * 1000.0
        metrics_tracker.observe_request(response.status_code, duration_ms)
        return response

























