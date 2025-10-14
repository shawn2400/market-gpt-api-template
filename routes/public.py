# routes/public.py
from __future__ import annotations
from fastapi import APIRouter

router = APIRouter(tags=["public"])

@router.get("/public/health")
def public_health():
    return {"ok": True, "service": "public", "msg": "alive"}

@router.get("/public/topk")
def public_topk():
    # החזר דמה; אפשר להחליף בהמשך בלוגיקה האמיתית
    return {"ok": True, "topk": [{"symbol": "BTCUSDT", "score": 9.1}, {"symbol": "ETHUSDT", "score": 8.7}]}
