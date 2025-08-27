# routes/anchor_extra.py
from __future__ import annotations
from fastapi import APIRouter, Depends
from typing import Dict
from utils.auth import require_api_key
from utils.anchor import evaluate_anchor

router = APIRouter(
    prefix="/anchor",
    tags=["AnchorExtra"],
    dependencies=[Depends(require_api_key)]
)

@router.get("/live")
def anchor_live() -> Dict[str, Dict]:
    """Anchor בזמן אמת לשני הצדדים"""
    return {
        "LONG": evaluate_anchor("LONG").__dict__,
        "SHORT": evaluate_anchor("SHORT").__dict__
    }
