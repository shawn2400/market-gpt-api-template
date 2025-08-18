# routes/snapshot.py
from __future__ import annotations
from typing import Dict, Any
from fastapi import APIRouter, Depends, Body
import os

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

from utils.snapshot_utils import save_trade_snapshot

router = APIRouter(prefix="/snapshot", tags=["Snapshots"], dependencies=[Depends(require_bearer_token)])

@router.post("/trade", summary="Create trade snapshot (PNG) and return its URL", operation_id="postTradeSnapshot")
async def post_trade_snapshot(payload: Dict[str, Any] = Body(..., embed=False)) -> Dict[str, Any]:
    """
    מצפה ל-json בסגנון:
    {
      "symbol": "BTCUSDT",
      "direction": "LONG" | "SHORT",
      "entry": 100.0,
      "stop": 95.0,
      "tp": 110.0,
      "price_now": 101.2,
      "budget": 50,
      "leverage": 10,
      "quality_score": 8.3
    }
    """
    path = save_trade_snapshot(payload)
    if not path:
        return {"ok": False, "detail": "Failed to render snapshot (check entry/stop/tp are positive)"}

    rel_path = path.replace("\\", "/")
    if rel_path.startswith("static/"):
        rel_path = "/" + rel_path  # => /static/...

    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    url = f"{base}{rel_path}" if base else rel_path

    return {"ok": True, "file_path": path, "url": url}

