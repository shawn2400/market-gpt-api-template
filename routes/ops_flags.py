# routes/ops_flags.py
from __future__ import annotations
import os
from fastapi import APIRouter, Depends

try:
    from utils.auth import require_api_key
except Exception:
    def require_api_key():
        return True

router = APIRouter(prefix="/ops/flags", tags=["ops-flags"], dependencies=[Depends(require_api_key)])

def _as_bool(s: str | None, default: bool = False) -> bool:
    return str(s).strip().lower() in {"1","true","yes","on"} if s is not None else default

@router.get("")
def flags_status():
    return {
        "ok": True,
        "flags": {
            "APPROVAL_ENABLED": _as_bool(os.getenv("APPROVAL_ENABLED","1"), True),
            "EXECUTE_TRADES": _as_bool(os.getenv("EXECUTE_TRADES","1"), True),
            "GRID_ENABLE": _as_bool(os.getenv("GRID_ENABLE","1"), True),
            "DYNAMIC_POLICY_ENABLE": _as_bool(os.getenv("DYNAMIC_POLICY_ENABLE","1"), True),
            "CALIB_ENABLE": _as_bool(os.getenv("CALIB_ENABLE","0"), False),
        }
    }



