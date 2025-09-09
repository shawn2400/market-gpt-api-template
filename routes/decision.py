# routes/decision.py
from __future__ import annotations
import asyncio
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, Body
from utils.auth import require_api_key

# נסה להביא את המנוע אם קיים; אחרת נשתמש בניהול פנימי פשוט
try:
    from utils.decision_engine import select_best_trades  # type: ignore
except Exception:
    def select_best_trades(cands: List[Dict[str, Any]], top_n: int = 5, diversify_by_symbol: bool = True):
        # דירוג בסיסי: score יורד, ואז by speed/ts עולה, ואפשר גיוון לפי סמל
        cands = list(cands or [])
        for c in cands:
            c["__score__"] = float(c.get("score") or 0.0)
            c["__time__"]  = float(c.get("speed") or c.get("ts") or 0.0)
        cands.sort(key=lambda x: (-x["__score__"], x["__time__"]))
        if not diversify_by_symbol:
            return cands[:top_n]
        seen = set(); out = []
        for c in cands:
            sym = str(c.get("symbol") or "").upper()
            if sym in seen: continue
            out.append(c); seen.add(sym)
            if len(out) >= top_n: break
        return out

router = APIRouter(prefix="/decision", tags=["Analytics"], dependencies=[Depends(require_api_key)])

@router.post("/best-trades", summary="Select best trades (quality/speed/diversify)")
async def post_best_trades(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    cands = payload.get("candidates") or []
    top_n = int(payload.get("top_n") or 5)
    diversify = bool(payload.get("diversify_by_symbol", True))
    selected = await asyncio.to_thread(select_best_trades, cands, top_n, diversify)
    return {"ok": True, "selected": selected, "note": f"diversify={diversify}, top_n={top_n}"}







