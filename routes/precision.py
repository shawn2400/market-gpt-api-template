# routes/precision.py
from __future__ import annotations
from typing import Dict, Any
from fastapi import APIRouter, Depends, Query
from utils.auth import require_api_key
from utils.precision import fix_order

router = APIRouter(prefix="/precision", tags=["Precision"], dependencies=[Depends(require_api_key)])

@router.get("/fix")
def api_fix(
    symbol: str = Query(...),
    price: float = Query(...),
    qty: float = Query(...),
    market: str = Query("futures")
) -> Dict[str, Any]:
    """
    מחזיר price/qty מתוקננים לפי tickSize/stepSize כדי למנוע דחיות ('Precision').
    """
    return fix_order(symbol, price, qty, market)
