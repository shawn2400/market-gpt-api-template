# routes/metrics.py
from __future__ import annotations
import os
from fastapi import APIRouter, Header, HTTPException, Response
from utils.metrics_tracker import render_prometheus_text  # מייצר את ה-Exposition Text

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
    body = render_prometheus_text()
    # הפורמט התקני של Prometheus exposition
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")



