# routes/manage_state.py
from __future__ import annotations

import os
import time
from typing import List, Dict, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

from schemas.manage_state import TradesStateOut, TradeStateItem  # type: ignore

try:
    from storage.trades_store import get_all_state  # type: ignore
except Exception:
    def get_all_state() -> List[Dict[str, Any]]:  # type: ignore
        return []

router = APIRouter(prefix="/ops", tags=["ops-state"], dependencies=[Depends(require_bearer_token)])

@router.get("/manager/health", summary="Manager health")
def manager_health():
    return {"ok": True, "ts": int(time.time()), "instance": os.getenv("INSTANCE_ID") or os.getenv("APP_NAME", "algogpt")}

@router.get("/state/trades", response_model=TradesStateOut, summary="All trades state (debug)")
def state_trades() -> TradesStateOut:
    raw = get_all_state() or []
    items = []
    for t in raw:
        try:
            items.append(TradeStateItem(**t))
        except Exception:
            # normalize minimal subset
            items.append(TradeStateItem(
                trade_id=str(t.get("trade_id", "")),
                symbol=str(t.get("symbol", "")),
                side=str(t.get("side", "")),
                qty=float(t.get("qty", 0) or 0),
                leverage=int(t.get("leverage", 0) or 0),
                state=str(t.get("state", "UNKNOWN")),
                entry=float(t.get("entry") or 0) or None,
                opened_ts=float(t.get("opened_ts") or 0) or None,
                extra=t.get("extra") or None,
            ))
    return TradesStateOut(ok=True, count=len(items), items=items)
