# routes/anchor.py
from __future__ import annotations
import json, time, logging
from typing import List, Dict, Any
from fastapi import APIRouter, Query, HTTPException, Request, Depends
from pydantic import BaseModel, Field

from utils.redis_client import redis_client
from utils.anchor import evaluate_anchor, AnchorDecision
from utils.auth import require_api_key

logger = logging.getLogger("algogpt.anchor")

router = APIRouter(tags=["Anchor"], prefix="/anchor", dependencies=[Depends(require_api_key)])

# --- Rate-limit פשוט בזיכרון ---
_rl_state: Dict[str, list] = {}
def _rl(ip: str, limit=20, window=60):
    now = time.time()
    calls = [c for c in _rl_state.get(ip, []) if now - c < window]
    if len(calls) >= limit:
        return False
    calls.append(now)
    _rl_state[ip] = calls
    return True

# --- Models ---
class AnchorSnapshot(BaseModel):
    ts: int
    side: str
    bias: str
    score: float
    allow: bool

class AnchorHistoryResponse(BaseModel):
    ok: bool = True
    count: int
    items: List[AnchorSnapshot] = Field(default_factory=list)

class AnchorLiveResponse(BaseModel):
    ok: bool = True
    side: str
    decision: Dict[str, Any]

# --- Endpoints ---
@router.get("/history", response_model=AnchorHistoryResponse)
async def get_anchor_history(
    limit: int = Query(20, ge=10, le=200),
    request: Request = None,
):
    if request and not _rl(request.client.host):
        raise HTTPException(429, "Rate limit exceeded")

    items: List[AnchorSnapshot] = []
    try:
        if not redis_client:
            logger.warning("⚠️ Redis not initialized, returning empty history")
            return AnchorHistoryResponse(ok=True, count=0, items=[])

        raw_items = redis_client.lrange("anchor:history", 0, limit - 1) or []
        for raw in raw_items:
            try:
                items.append(AnchorSnapshot(**json.loads(raw)))
            except Exception:
                continue
        return AnchorHistoryResponse(ok=True, count=len(items), items=items)
    except Exception as e:
        logger.error(f"⚠️ Anchor history fetch failed: {e}")
        return AnchorHistoryResponse(ok=False, count=0, items=[])

@router.get("/live", response_model=AnchorLiveResponse)
async def get_anchor_live(
    side: str = Query("LONG", regex="^(LONG|SHORT)$"),
    request: Request = None,
):
    if request and not _rl(request.client.host):
        raise HTTPException(429, "Rate limit exceeded")

    dec: AnchorDecision = evaluate_anchor(side)
    return AnchorLiveResponse(
        ok=True,
        side=side,
        decision={
            "mode_requested": getattr(dec, "mode_requested", None),
            "mode_applied": getattr(dec, "mode_applied", None),
            "bias": getattr(dec, "bias", None),
            "score": getattr(dec, "score", None),
            "allow": getattr(dec, "allow", None),
            "severity": getattr(dec, "severity", None),
            "reason": getattr(dec, "reason", None),
        },
    )






