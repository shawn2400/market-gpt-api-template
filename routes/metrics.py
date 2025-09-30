# routes/metrics.py
from __future__ import annotations
from fastapi import APIRouter, Query
from utils.metrics import metrics_tracker

router = APIRouter(tags=["Metrics"])

@router.get("/metrics-json")
def metrics_json(prefix: str = Query("", description="סינון לפי prefix לשמות מטריקות (אופציונלי)")):
    data = metrics_tracker.get_metrics()
    if prefix:
        pref = prefix.strip()
        data["counters"] = {k: v for k, v in data.get("counters", {}).items() if k.startswith(pref)}
        data["gauges"]   = {k: v for k, v in data.get("gauges", {}).items() if k.startswith(pref)}
    return data

@router.get("/metrics/health")
def metrics_health():
    # בריאות מינימלית – שימושי ל־k8s
    m = metrics_tracker.get_metrics()
    return {
        "ok": True,
        "uptime_sec": max(0, (m["now_ts"] - (m["started_ts"] or m["now_ts"]))),
        "series": {
            "counters": len(m.get("counters", {})),
            "gauges": len(m.get("gauges", {})),
        },
    }


