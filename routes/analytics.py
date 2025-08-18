# routes/analytics.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Query

# --- Macro snapshot (DXY/NDX/SPX/F&G/BTC.D) ---
def _macro_snapshot() -> Dict[str, Any]:
    try:
        from utils.macro import macro_snapshot  # type: ignore
        res = macro_snapshot()
        # שמירה על פורמט צפוי
        if isinstance(res, dict) and "ok" in res:
            return res
    except Exception:
        pass
    return {"ok": False, "note": "macro provider not configured"}

# --- Onchain overview (BTC/ETH) ---
def _onchain_overview(targets: List[str]) -> Dict[str, Any]:
    try:
        from utils.onchain import overview  # type: ignore
        data = overview(targets)
        if isinstance(data, dict) and "ok" in data:
            return data
    except Exception:
        pass
    # fallback ריק – לא 404
    return {
        "ok": True,
        "chains": {t: {"ok": False, "warnings": ["onchain provider not configured"]} for t in targets}
    }

# --- Sentiment (סיכום -100..100) ---
def _sentiment_summary() -> Dict[str, Any]:
    try:
        from utils.sentiment import summary  # type: ignore
        s = summary()
        if isinstance(s, dict) and "ok" in s:
            return s
    except Exception:
        pass
    return {"ok": True, "score": 0.0, "buckets": {}, "samples": 0}

router = APIRouter(tags=["Analytics"])

@router.get("/analytics/macro", summary="Macro snapshot (DXY/NDX/SPX/FG/BTC.D)", operation_id="getMacro")
async def get_macro() -> Dict[str, Any]:
    return _macro_snapshot()

@router.get("/onchain/overview", summary="On-chain overview (BTC/ETH)", operation_id="getOnchainOverview")
async def get_onchain_overview(
    targets: Optional[str] = Query(None, description="Comma-separated chains, e.g. BTC,ETH"),
) -> Dict[str, Any]:
    lst = []
    if targets:
        lst = [t.strip().upper() for t in targets.split(",") if t.strip()]
    if not lst:
        lst = ["BTC", "ETH"]
    return _onchain_overview(lst)

@router.get("/sentiment/summary", summary="Sentiment summary (-100..100)", operation_id="getSentiment")
async def get_sentiment() -> Dict[str, Any]:
    return _sentiment_summary()


































