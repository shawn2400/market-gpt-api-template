# routes/metrics.py
from __future__ import annotations
import os
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import PlainTextResponse
from utils.metrics_tracker import get_prom_metrics_text

router = APIRouter(prefix="", tags=["Metrics"])

_METRICS_BEARER = (os.getenv("METRICS_BEARER") or "").strip()

@router.get("/metrics", summary="Prometheus metrics (plain text)")
async def metrics(authorization: str = Header(default="")):
    if _METRICS_BEARER:
        if not (authorization.startswith("Bearer ") and authorization.split(" ", 1)[1].strip() == _METRICS_BEARER):
            raise HTTPException(status_code=401, detail="Unauthorized")
    return PlainTextResponse(get_prom_metrics_text(), media_type="text/plain; version=0.0.4; charset=utf-8")
