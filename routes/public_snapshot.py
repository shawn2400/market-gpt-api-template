# routes/public_snapshot.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/public/snapshot", tags=["Public Feed"])

# Bearer ACTION (כתיבה)
_ACTION = (os.getenv("API_BEARER_TOKEN_ACTION") or "").strip()
_REQUIRE_ACTION = os.getenv("PUBLIC_SNAPSHOT_REQUIRE_ACTION", "1").lower() in ("1","true","yes","on")

SNAP_DIR = os.getenv("PUBLIC_SNAPSHOT_DIR", "static/cache")
SNAP_FILE = os.path.join(SNAP_DIR, "public_snapshots.jsonl")

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
    if side == "L":
        side = "LONG"
    if side == "S":
        side = "SHORT"

    def _coerce_float(x):
        try:
            return float(x)
        except Exception:
            return None

    clean: Dict[str, Any] = {"symbol": sym, "side": side or None}
    for k in ("score", "entry", "now", "pnl"):
        if k in payload:
            v = _coerce_float(payload.get(k))
            if v is not None:
                clean[k] = v
    if "sl" in payload:
        clean["sl"] = payload["sl"]
    if "tp" in payload:
        if isinstance(payload["tp"], list):
            clean["tp"] = payload["tp"][:6]
        else:
            raise HTTPException(status_code=422, detail="tp must be list")
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
    os.makedirs(SNAP_DIR, exist_ok=True)
    rec = {"ts": int(time.time()), **clean}
    with open(SNAP_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return JSONResponse({"ok": True, "snapshot": rec, "path": SNAP_FILE})

@router.get("/inspect", summary="Inspect snapshot for a symbol")
async def snapshot_inspect(symbol: str = Query(...)):
    if not os.path.exists(SNAP_FILE):
        raise HTTPException(status_code=404, detail="not found")
    last = None
    with open(SNAP_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
                if (j.get("symbol") or "").upper() == symbol.upper():
                    last = j
            except Exception:
                continue
    if not last:
        raise HTTPException(status_code=404, detail="not found")
    return JSONResponse({"ok": True, "snapshot": last})

@router.get("/symbols", summary="List symbols with snapshot (best-effort)")
async def snapshot_symbols():
    syms = set()
    if os.path.exists(SNAP_FILE):
        with open(SNAP_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    j = json.loads(line)
                    s = (j.get("symbol") or "").upper()
                    if s:
                        syms.add(s)
                except Exception:
                    continue
    return {"ok": True, "symbols": sorted(list(syms))}

