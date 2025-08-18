from __future__ import annotations
from fastapi import APIRouter

router = APIRouter(prefix="/analytics", tags=["Analytics"])
router_compat = APIRouter(tags=["Analytics"])  # ללא prefix

@router.get("/macro", operation_id="getMacro", summary="Macro snapshot (DXY/NDX/SPX/FG/BTC.D)")
async def get_macro():
    # אם אין מפתחות/פיד אמיתי — מחזיר מבנה ריק תקין
    return {"ok": True, "dxy": None, "ndx": None, "spx": None, "btc_dominance": None, "fear_greed": None, "updated_at": None, "note": "no provider configured"}

@router_compat.get("/macro", operation_id="getMacroCompat", summary="Macro (alias for /analytics/macro)")
async def get_macro_compat():
    return await get_macro()




































