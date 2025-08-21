# routes/anchor.py
from __future__ import annotations
from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel
from typing import Literal, List
import time, json

# --- Auth
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

# --- Redis
try:
    from utils.redis_client import redis_client
except Exception:
    redis_client = None

# --- Anchor engine
from utils.anchor import evaluate_anchor, AnchorDecision

router = APIRouter(
    prefix="/anchor",
    tags=["Anchor"],
    dependencies=[Depends(require_bearer_token)]
)

Side = Literal["LONG", "SHORT"]

# =========================
# Models
# =========================
class AnchorResponse(BaseModel):
    mode_requested: str
    mode_applied: str
    bias: str
    score: float
    allow: bool
    severity: str
    reason: str

    @classmethod
    def from_decision(cls, d: AnchorDecision) -> "AnchorResponse":
        return cls(
            mode_requested=d.mode_requested,
            mode_applied=d.mode_applied,
            bias=d.bias,
            score=d.score,
            allow=d.allow,
            severity=d.severity,
            reason=d.reason,
        )

class AnchorHistoryItem(BaseModel):
    ts: int
    side: Side
    bias: str
    score: float
    allow: bool

class AnchorHistoryResponse(BaseModel):
    ok: bool = True
    count: int
    items: List[AnchorHistoryItem]

# =========================
# Endpoints
# =========================
@router.get("/status", response_model=AnchorResponse, summary="Get BTC Anchor status")
async def get_anchor_status(side: Side = Query("LONG")):
    decision = evaluate_anchor(side)

    # שמירה בהיסטוריה (רק אם יש Redis)
    if redis_client:
        key = "anchor:history"
        item = {
            "ts": int(time.time()),
            "side": side,
            "bias": decision.bias,
            "score": decision.score,
            "allow": decision.allow,
        }
        try:
            redis_client.lpush(key, json.dumps(item))
            redis_client.ltrim(key, 0, 200)  # נשמור רק 200 רשומות אחרונות
        except Exception:
            pass

    return AnchorResponse.from_decision(decision)

@router.get("/history", response_model=AnchorHistoryResponse, summary="Get BTC Anchor history")
async def get_anchor_history(limit: int = Query(50, ge=10, le=200)):
    items: List[AnchorHistoryItem] = []
    if redis_client:
        try:
            key = "anchor:history"
            raw_items = redis_client.lrange(key, 0, limit - 1) or []
            for raw in raw_items:
                try:
                    data = json.loads(raw)
                    items.append(AnchorHistoryItem(**data))
                except Exception:
                    continue
        except Exception:
            pass
    return AnchorHistoryResponse(ok=True, count=len(items), items=items)










