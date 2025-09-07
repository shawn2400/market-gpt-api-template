# routes/risk_tools.py
from __future__ import annotations
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import math, os, httpx, logging

logger = logging.getLogger("algogpt.risk_tools")

router = APIRouter(prefix="/risk", tags=["Risk"])

ALERTS_ACTIVE_URL = os.getenv("ALERTS_ACTIVE_URL", "http://127.0.0.1:8000/alerts/trades/active").strip()

class RiskResult(BaseModel):
    ok: bool = True
    symbol: str
    side: str
    entry: float
    sl: float
    tp1: Optional[float] = None
    rr: Optional[float] = None
    success_pct: Optional[float] = None
    kelly_fraction: Optional[float] = None
    leverage_cap: Optional[int] = None
    notes: Dict[str, Any] = {}

def _rr(entry: float, sl: float, tp: Optional[float], side: str) -> Optional[float]:
    if not (entry and sl and tp):
        return None
    try:
        if side == "LONG":
            risk = entry - sl
            reward = tp - entry
        else:
            risk = sl - entry
            reward = entry - tp
        if risk <= 0 or reward <= 0:
            return None
        return reward / risk
    except Exception:
        return None

def _kelly(p: float, R: float) -> Optional[float]:
    if not R or R <= 0:
        return None
    f = p - (1 - p) / R
    return max(0.0, min(0.25, f))

def _lev_cap(entry: float, sl: float) -> Optional[int]:
    if not (entry and sl):
        return None
    stop_pct = abs(entry - sl) / entry
    if stop_pct <= 0:
        return None
    cap = math.floor(1.0 / (stop_pct * 1.8))
    return max(1, min(25, cap))

@router.get("/quick", response_model=RiskResult)
async def risk_quick(trade_id: str = Query(...)):
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(ALERTS_ACTIVE_URL)
            r.raise_for_status()
            items = r.json().get("items", [])
    except Exception as e:
        logger.error(f"risk_quick fetch failed: {e}")
        raise HTTPException(502, "alerts service unavailable")

    rec = next((it for it in items if str(it.get("trade_id")) == trade_id), None)
    if not rec:
        raise HTTPException(404, "trade not found")

    symbol = str(rec.get("symbol", "")).upper()
    side = str(rec.get("side", "LONG")).upper()
    entry = float(rec.get("entry") or 0)
    sl = float(rec.get("sl") or 0)
    tp1 = rec.get("tp1"); tp1 = float(tp1) if tp1 is not None else None
    success = rec.get("success_pct")
    success_pct = float(success) if success is not None else 55.0

    R = _rr(entry, sl, tp1, side)
    k = _kelly(success_pct / 100.0, R if R else None)
    lev = _lev_cap(entry, sl)

    notes = {}
    if R is None:
        notes["rr_note"] = "RR לא תקין/חסר (בדוק Entry/SL/TP1)."
    if k is not None and k > 0.2:
        notes["kelly_note"] = "Kelly גבוה — שקול לחצות אותו (Kelly/2)."

    return RiskResult(
        ok=True,
        symbol=symbol,
        side=side,
        entry=entry,
        sl=sl,
        tp1=tp1,
        rr=R,
        success_pct=success_pct,
        kelly_fraction=k,
        leverage_cap=lev,
        notes=notes,
    )

