# routes/metrics.py
from __future__ import annotations
from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest, REGISTRY

router = APIRouter(tags=["Metrics"])

@router.get("/metrics")
def get_metrics():
    data = generate_latest(REGISTRY)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

