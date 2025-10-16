# routes/metrics.py
from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse
import os

try:
    from utils.metrics_tracker import render_prometheus_text  # type: ignore
except Exception:
    def render_prometheus_text() -> str:  # type: ignore
        return "# no metrics\n"

router = APIRouter(tags=["metrics"])

def _require_metrics_bearer(request: Request) -> None:
    """
    אם METRICS_ENABLE=false => 404
    אם METRICS_BEARER לא מוגדר => ציבורי
    אחרת => דורש Authorization: Bearer <token>
    """
    if os.getenv("METRICS_ENABLE", "true").lower() not in ("1", "true", "yes", "on"):
        raise HTTPException(status_code=404, detail="metrics disabled")
    token = os.getenv("METRICS_BEARER", "").strip()
    if not token:
        return
    auth = request.headers.get("Authorization", "")
    if not (auth.startswith("Bearer ") and auth.split(" ", 1)[1].strip() == token):
        raise HTTPException(status_code=401, detail="unauthorized")

@router.get("/metrics", response_class=PlainTextResponse, summary="Prometheus metrics")
async def metrics(request: Request):
    _require_metrics_bearer(request)
    txt = render_prometheus_text()
    return PlainTextResponse(txt, media_type="text/plain; version=0.0.4")





