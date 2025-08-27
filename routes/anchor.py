# routes/anchor_extra.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, List, Any
import json

from utils.auth import require_api_key
from utils.anchor import evaluate_anchor
from utils import cache_fallback as redis_store

router = APIRouter(
    prefix="/anchor",
    tags=["Anchor"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/history", response_model=List[Dict[str, Any]])
async def anchor_history(limit: int = 50):
    """היסטוריית Anchor מה־Redis (אם קיים)"""
    try:
        data = await redis_store.lrange("anchor:history", 0, limit - 1)
        return [json.loads(x) for x in data] if data else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch anchor history: {e}")

@router.get("/live", response_model=Dict[str, Any])
def anchor_live():
    """Anchor עדכני (LONG + SHORT)"""
    try:
        return {
            "LONG": evaluate_anchor("LONG", mode="soft").__dict__,
            "SHORT": evaluate_anchor("SHORT", mode="soft").__dict__,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to evaluate anchor: {e}")










