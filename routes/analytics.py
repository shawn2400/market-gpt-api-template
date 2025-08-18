# routes/analytics.py
from __future__ import annotations
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Query

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/macro", summary="Macro snapshot (DXY/NDX/SPX/FG/BTC.D)", operation_id="getMacro")
def get_macro() -> Dict[str, Any]:
    # מנסה utils.macro; אם נכשל – לא 404, מחזיר הודעה ידידותית
    try:
        from utils.macro import macro_snapshot  # type: ignore
        snap = macro_snapshot()
        if isinstance(snap, dict):
            return snap
    except Exception:
        pass
    return {"ok": False, "note": "macro provider not configured"}

@router.get("/onchain/overview", summary="On-chain overview (BTC/ETH)", operation_id="getOnchainOverview")
def get_onchain_overview(
    targets: Optional[List[str]] = Query(default=None, description="Comma separated: BTC,ETH")
) -> Dict[str, Any]:
    tg: List[str] = []
    if targets:
        tg = [str(x).strip().upper() for x in targets if str(x).strip()]
    if not tg:
        tg = ["BTC","ETH"]
    try:
        # ספק פנימי אם קיים
        from utils.onchain import overview as onchain_overview  # type: ignore
        data = onchain_overview(tg)  # מצופה להחזיר dict עם מפת chain->info
        if isinstance(data, dict):
            return {"ok": True, "chains": data}
    except Exception:
        pass
    # fallback: לא מפילים 404/500
    return {"ok": True, "chains": {c: {"ok": True, "warnings": ["onchain provider not configured"]}} for c in tg}





