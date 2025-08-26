# routes/topk.py
from __future__ import annotations
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import List
from utils.watchlist_utils import build_symbol_pool

topk_router = APIRouter()

class TopKOut(BaseModel):
    ok: bool = True
    symbols: List[str]

@topk_router.get("/topk", response_model=TopKOut)
def context_topk(
    k: int = Query(12, ge=1, le=50),
    min_quality: int = Query(6, ge=0, le=10),
    include_anchor: bool = Query(True),
    include_shorts: bool = Query(True),
    balanced: bool = Query(True),
    explore_prob: float = Query(0.15, ge=0.0, le=1.0),
) -> TopKOut:
    syms = build_symbol_pool(
        k=k, min_quality=min_quality,
        include_anchor=include_anchor,
        include_shorts=include_shorts,
        balanced=balanced,
        explore_prob=explore_prob,
    )
    return TopKOut(ok=True, symbols=syms)



