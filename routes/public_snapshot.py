# routes/public_snapshot.py
from __future__ import annotations
import os
from typing import Any, Dict, Optional
from fastapi import APIRouter, Header, HTTPException, Body, Query
from fastapi.responses import JSONResponse

from utils.snapshot_store import upsert_snapshot, get_snapshot, list_symbols, touch_symbol

router = APIRouter(prefix="/public/snapshot", tags=["Public Feed"])

# Bearer ACTION (כתיבה)
_ACTION = (os.getenv("API_BEARER_TOKEN_ACTION") or "").strip()
_REQUIRE_ACTION = os.getenv("PUBLIC_SNAPSHOT_REQUIRE_ACTION", "1").lower() in ("1","true","yes","on")

def _check_action_bearer(authorization: Optional[str]) -> None:
    if not _REQUIRE_ACTION:
        return
    if not _ACTION:
        raise HTTPException(status_code=500, detail="missing action token in server config")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer")
    token = authorization.split(" ", 1)[1].strip()
    if token != _ACTION:
        raise HTTPException(status_code=401, detail="bad bearer")

def _validate_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    sym = str(payload.get("symbol", "")).strip().upper()
    side = str(payload.get("side", "")).strip().upper()
    if not sym:
        raise HTTPException(status_code=422, detail="symbol required")
    if side not in ("LONG", "SHORT", "L", "S", ""):
        raise HTTPException(status_code=422, detail="bad side")
    # normalize
    if side == "L":
        side = "LONG"
    if side == "S":
        side = "SHORT"

    # optional numeric coercions
    def _coerce_float(x):
        try:
            return float(x)
        except Exception:
            return None

    clean: Dict[str, Any] = {
        "symbol": sym,
        "side": side or None,
    }
    for k in ("score", "entry", "now", "pnl"):
        if k in payload:
            v = _coerce_float(payload.get(k))
            if v is not None:
                clean[k] = v

    # sl/tp as-is (basic shape)
    if "sl" in payload:
        clean["sl"] = payload["sl"]
    if "tp" in payload:
        if isinstance(payload["tp"], list):
            clean["tp"] = payload["tp"][:6]  # small cap to stay safe
        else:
            raise HTTPException(status_code=422, detail="tp must be list")

    # meta/extra
    if "meta" in payload and isinstance(payload["meta"], dict):
        clean["meta"] = payload["meta"]

    return clean

@router.post("/upsert", summary="Upsert public snapshot (ACTION bearer)")
async def snapshot_upsert(
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
):
    _check_action_bearer(authorization)
    clean = _validate_snapshot(body)
    snap = await upsert_snapshot(clean)
    await touch_symbol(clean["symbol"])
    return JSONResponse({"ok": True, "snapshot": snap})

@router.get("/inspect", summary="Inspect snapshot for a symbol")
async def snapshot_inspect(symbol: str = Query(...)):
    snap = await get_snapshot(symbol)
    if not snap:
        raise HTTPException(status_code=404, detail="not found")
    return JSONResponse({"ok": True, "snapshot": snap})

@router.get("/symbols", summary="List symbols with snapshot (best-effort)")
async def snapshot_symbols():
    syms = await list_symbols()
    return {"ok": True, "symbols": syms}
