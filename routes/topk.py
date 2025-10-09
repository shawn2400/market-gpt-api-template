# routes/topk.py
from __future__ import annotations
from typing import List, Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel

# נסה לבנות מאגר סמלים אמיתי; אם חסר יוטיל – נשתמש בפולבאק פשוט
try:
    from utils.watchlist_utils import build_symbol_pool  # type: ignore
except Exception:
    def build_symbol_pool(
        k: int = 12,
        min_quality: int = 6,
        include_anchor: bool = True,
        include_shorts: bool = True,
        balanced: bool = True,
        explore_prob: float = 0.15,
    ) -> List[str]:
        base = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"]
        return base[: max(1, min(k, len(base)))]

router = APIRouter(prefix="/topk", tags=["TopK"])

class TopKOut(BaseModel):
    ok: bool = True
    symbols: List[str]

@router.get("", response_model=TopKOut, summary="Top-K universe pick")
def topk_root(
    k: int = Query(12, ge=1, le=50),
    min_quality: int = Query(6, ge=0, le=10),
    include_anchor: bool = Query(True),
    include_shorts: bool = Query(True),
    balanced: bool = Query(True),
    explore_prob: float = Query(0.15, ge=0.0, le=1.0),
    # Alias תאימות: limit
    limit: Optional[int] = Query(None, ge=1, le=50, description="Alias for k"),
) -> TopKOut:
    if limit is not None:
        k = limit
    syms = build_symbol_pool(
        k=k,
        min_quality=min_quality,
        include_anchor=include_anchor,
        include_shorts=include_shorts,
        balanced=balanced,
        explore_prob=explore_prob,
    )
    return TopKOut(ok=True, symbols=syms)



