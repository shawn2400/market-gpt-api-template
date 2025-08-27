# routes/anchor_extra.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, List
import json

from utils.auth import require_api_key
from utils.anchor import evaluate_anchor
from utils import cache_fallback as redis_store

router = APIRouter(
    prefix="/anchor",
    tags=["AnchorExtra"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/live")
def anchor_live() -> Dict[str, Dict[str, Any]]:
    """Anchor בזמן אמת לשני הצדדים (LONG/SHORT)"""
    return {
        "LONG": evaluate_anchor("LONG").__dict__,
        "SHORT": evaluate_anchor("SHORT").__dict__
    }

@router.get("/history")
async def anchor_history(limit: int = 50) -> List[Dict[str, Any]]:
    """Anchor היסטורי מתוך Redis (עד limit אחרונים)"""
    try:
        data = await redis_store.lrange("anchor:history", 0, limit - 1)
        return [json.loads(x) for x in data] if data else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch anchor history: {e}")


