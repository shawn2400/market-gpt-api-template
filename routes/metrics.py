# routes/metrics.py
from __future__ import annotations
import os, json, time
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Query, HTTPException
from utils.metrics import metrics_tracker

# לא /metrics (כבר ממופה ב-main.py ל-Prometheus). כאן JSON קל לעבודה.
router = APIRouter(tags=["Metrics"])

@router.get("/metrics-json")
def metrics_json():
    """
    מחזיר את כלל המטריקות הפנימיות כ-JSON קל לצריכה.
    """
    return metrics_tracker.get_metrics()

@router.get("/metrics-json/top-expired")
async def metrics_json_top_expired(
    hours: int = Query(6, ge=1, le=48),
    limit: int = Query(10, ge=1, le=50),
):
    """
    אגרגציית top-N לכרטיסים שפג תוקפם (symbol/side) לפי לוג ה-Redis (ללא עומס/JQ).
    דורש שה-GC ירשום ליסט NS:expired_log (כבר קיים בקוד ה-GC המצורף).
    """
    try:
        import redis.asyncio as aioredis  # type: ignore
    except Exception:
        aioredis = None  # type: ignore

    NS = os.getenv("REDIS_NAMESPACE","ops-supervisor-web").strip() or "ops-supervisor-web"
    REDIS_URL = os.getenv("REDIS_URL","").strip()
    if not (aioredis and REDIS_URL):
        raise HTTPException(status_code=503, detail="redis_unavailable")

    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    key = f"{NS}:expired_log"
    now = time.time()
    since = now - (hours * 3600)
    items = await r.lrange(key, 0, 2000)

    from collections import Counter
    c = Counter()
    last_events: List[Dict[str, Any]] = []
    for it in items:
        try:
            obj = json.loads(it)
            if float(obj.get("ts", 0)) >= since:
                sym = (obj.get("symbol") or "").upper()
                side = (obj.get("side") or "").upper()
                c[(sym, side)] += 1
                last_events.append(obj)
        except Exception:
            continue

    top = [ {"symbol": k[0], "side": k[1], "count": v}
            for k, v in c.most_common(limit) ]

    last_events.sort(key=lambda x: x.get("ts", 0), reverse=True)
    preview = [{
        "ts": int(e.get("ts", now)),
        "symbol": (e.get("symbol") or "").upper(),
        "side": (e.get("side") or "").upper(),
        "idem": e.get("idem","")
    } for e in last_events[:min(5, len(last_events))]]

    return {
        "ok": True,
        "window_hours": hours,
        "top": top,
        "last_sample": preview,
        "total_in_window": sum(x["count"] for x in top)
    }


