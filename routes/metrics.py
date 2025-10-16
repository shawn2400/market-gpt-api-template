# routes/metrics.py
from __future__ import annotations
from fastapi import APIRouter, Response
from utils.metrics_tracker import render_prometheus_text  # type: ignore

router = APIRouter(prefix="", tags=["metrics"])

@router.get("/metrics")
async def metrics():
    body = render_prometheus_text()
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")





