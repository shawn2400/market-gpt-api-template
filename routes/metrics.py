# routes/metrics.py
from __future__ import annotations
import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse
from utils.metrics_tracker import render_prometheus_text

router = APIRouter(tags=["Metrics"])

def _require_metrics_bearer(request: Request) -> None:
    if os.getenv("METRICS_PROTECT", "0").lower() not in ("1","true","yes","on"):
        return
    expected = (os.getenv("METRICS_BEARER") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="metrics_protect_enabled_but_token_missing")
    auth = request.headers.get("Authorization", "")
    if not (auth.startswith("Bearer ") and auth.split(" ", 1)[1].strip() == expected):
        raise HTTPException(status_code=401, detail="unauthorized")

@router.get(os.getenv("PROM_METRICS_PATH", "/metrics"), include_in_schema=False)
async def metrics(request: Request):
    if os.getenv("PROM_METRICS_ENABLE", "0").lower() not in ("1","true","yes","on"):
        raise HTTPException(status_code=404, detail="metrics_disabled")
    _require_metrics_bearer(request)
    return PlainTextResponse(render_prometheus_text(), media_type="text/plain; version=0.0.4")




