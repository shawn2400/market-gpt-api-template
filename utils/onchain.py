# routes/onchain.py
from __future__ import annotations
import asyncio
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, Query, HTTPException

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        raise HTTPException(status_code=401, detail="Unauthorized")

from utils.onchain import get_onchain_overview

router = APIRouter(tags=["Analytics"], dependencies=[Depends(require_bearer_token)])

@router.get(
    "/onchain/overview",
    summary="On-chain overview (BTC/ETH)",
    operation_id="getOnchainOverview",
)
async def onchain_overview(
    targets: str = Query(
        "BTC,ETH",
        description="Comma-separated chains, e.g. BTC,ETH",
        examples=["BTC", "ETH", "BTC,ETH"],
    )
) -> Dict[str, Any]:
    """
    אגרגציית אונצ׳יין מהירה מ־public endpoints (ללא מפתח):
    - BTC: mempool.space (עמלות), blockchair (סטטיסטיקות)
    - ETH: blockchair (סטטיסטיקות + Gas)
    """
    target_list: List[str] = [t.strip().upper() for t in str(targets).split(",") if t.strip()]
    result = await asyncio.to_thread(get_onchain_overview, target_list or ["BTC", "ETH"])
    return result


