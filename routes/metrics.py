# routes/metrics.py
from __future__ import annotations
import os
from fastapi import APIRouter, Header, HTTPException, Response
from prometheus_client import REGISTRY, generate_latest
from utils.metrics_tracker import render_prometheus_text  # Legacy metrics (kept for compatibility)

router = APIRouter(prefix="", tags=["metrics"])

# אופציונלי: הגנה ב-Bearer
_METRICS_BEARER = (os.getenv("METRICS_BEARER") or "").strip()
_API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()
_REQUIRE_BEARER = os.getenv("PUBLIC_METRICS_REQUIRE_BEARER", "0").lower() in ("1", "true", "yes", "on")

def _auth_ok(auth_header: str) -> bool:
    # אם לא נדרש Bearer – פתוח (אלא אם הוגדר METRICS_BEARER מפורשות)
    if not (_REQUIRE_BEARER or _METRICS_BEARER):
        return True
    if not (auth_header and auth_header.startswith("Bearer ")):
        return False
    tok = auth_header.split(" ", 1)[1].strip()
    # מקבלים או METRICS_BEARER ייעודי או ה-API_BEARER_TOKEN הכללי
    if _METRICS_BEARER and tok == _METRICS_BEARER:
        return True
    if _API_BEARER_TOKEN and tok == _API_BEARER_TOKEN:
        return True
    return False

@router.get("/metrics", summary="Prometheus metrics (text exposition format)")
async def metrics(authorization: str = Header(default="")):
    if not _auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Combine legacy metrics with Prometheus client registry (includes all Counter/Gauge/Histogram from prometheus_client)
    legacy = render_prometheus_text()
    
    # Get all metrics from Prometheus client registry (includes metrics_dyn.py and others)
    try:
        prom_bytes = generate_latest(REGISTRY)
        prom_text = prom_bytes.decode("utf-8") if isinstance(prom_bytes, bytes) else str(prom_bytes)
    except Exception:
        prom_text = ""
    
    # Merge both (legacy first, then Prometheus client)
    body = f"{legacy}\n\n# === Prometheus Client Metrics ===\n{prom_text}"
    
    # הפורמט התקני של Prometheus exposition
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")



