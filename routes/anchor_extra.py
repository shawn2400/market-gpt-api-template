# routes/anchor_extra.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from utils.auth import require_api_key
from utils.anchor import evaluate_anchor

router = APIRouter(
    prefix="/anchor",
    tags=["AnchorExtra"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/live")
def anchor_live() -> Dict[str, Any]:
    """
    Anchor בזמן אמת לשני הצדדים (LONG + SHORT).
    מחזיר Bias + ציון איכות + החלטת Allow/Block.
    """
    try:
        return {
            "LONG": evaluate_anchor("LONG").__dict__,
            "SHORT": evaluate_anchor("SHORT").__dict__
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to evaluate anchor: {e}")

