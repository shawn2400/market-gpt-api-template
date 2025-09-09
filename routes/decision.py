# routes/decision.py
from __future__ import annotations
import asyncio
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, Body

from utils.auth import require_api_key

# נסיון לייבא את הפונקציה מהיוטיליטי; אם לא קיים – נשתמש בגיבוי מקומי בטוח.
try:
    from utils.decision_engine import select_best_trades as _select_best_trades  # type: ignore
except Exception:
    def _select_best_trades(candidates: List[Dict[str, Any]], top_n: int = 5, diversify: bool = True):
        """
        Fallback פשוט: ממיין לפי quality_score↓ ואז speed_score↓.
        אם diversify=True – שומר רק מועמד אחד לכל symbol.
        """
        cands = candidates or []
        cands.sort(key=lambda x: (float(x.get("quality_score", 0)), float(x.get("speed_score", 0))), reverse=True)
        out: List[Dict[str, Any]] = []
        seen = set()
        for c in cands:
            sym = str(c.get("symbol") or "").upper()
            if diversify and sym in seen:
                continue
            out.append(c)
            seen.add(sym)
            if len(out) >= max(1, int(top_n)):
                break
        return out

router = APIRouter(prefix="/decision", tags=["Analytics"], dependencies=[Depends(require_api_key)])

@router.post("/best-trades", summary="Select best trades (quality/speed/diversify)")
async def post_best_trades(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    cands = payload.get("candidates") or []
    top_n = int(payload.get("top_n") or 5)
    diversify = bool(payload.get("diversify_by_symbol", True))
    selected = await asyncio.to_thread(_select_best_trades, cands, top_n, diversify)
    return {"ok": True, "selected": selected, "note": f"diversify={diversify}, top_n={top_n}"}






