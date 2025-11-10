# routes/metrics.py
from __future__ import annotations
import os
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
_PROM_MULTIPROC_DIR = os.getenv("PROMETHEUS_MULTIPROC_DIR")
if _PROM_MULTIPROC_DIR:
    from prometheus_client import CollectorRegistry, multiprocess

    def _prom_registry():
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return registry
else:
    from prometheus_client import REGISTRY  # type: ignore

    def _prom_registry():
        return REGISTRY

router = APIRouter(prefix="", tags=["metrics"])
dev_metrics = APIRouter(prefix="/metrics/dev", tags=["metrics-dev"])

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
    body = generate_latest(_prom_registry())
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)


def _dev_guard():
    if os.getenv("ALLOW_DEV_METRICS_BUMP", "0").lower() not in ("1", "true", "yes", "on"):
        raise HTTPException(status_code=403, detail="DEV metrics bump disabled")


@dev_metrics.get("/bump", summary="DEV helper to bump Prometheus counters")
def bump_metrics(kind: str = "all", _=Depends(_dev_guard)):
    from utils.metrics import RISK_BLOCK, SL_REPLACE_ATTEMPT, STOP_VALIDATION_FAIL

    if kind in ("all", "*"):
        RISK_BLOCK.inc()
        SL_REPLACE_ATTEMPT.inc()
        STOP_VALIDATION_FAIL.inc()
    elif kind == "risk":
        RISK_BLOCK.inc()
    elif kind == "sl":
        SL_REPLACE_ATTEMPT.inc()
    elif kind == "stop":
        STOP_VALIDATION_FAIL.inc()
    else:
        raise HTTPException(status_code=400, detail="unknown kind")
    return {"ok": True, "kind": kind}



