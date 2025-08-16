# routes/health_full.py
from __future__ import annotations
import os
from fastapi import APIRouter, Depends
from utils.auth import require_bearer_token

router = APIRouter()

APP_VERSION = os.getenv("ALGOGPT_VERSION", "dev")
STRATEGY_VERSION = os.getenv("STRATEGY_VERSION", "dev")
GIT_COMMIT = os.getenv("GIT_COMMIT", "")
REQ_HASH = os.getenv("REQ_HASH", "")

# ✅ Health בסיסי
@router.get("/health", summary="Basic health")
async def health():
    return {"status": "ok", "version": APP_VERSION}

# ✅ גרסת אסטרטגיה
@router.get(
    "/health/strategy-version",
    summary="Return strategy version info",
    dependencies=[Depends(require_bearer_token)]
)
async def strategy_version():
    return {
        "status": "ok",
        "app_version": APP_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "git_commit": GIT_COMMIT,
        "req_hash": REQ_HASH,
    }

# ✅ בדיקת LIVE/Ready מהירה
@router.get(
    "/health/live",
    summary="LIVE readiness check",
    dependencies=[Depends(require_bearer_token)]
)
async def live_check():
    execute_trades = os.getenv("EXECUTE_TRADES", "false").lower() in ("1","true","yes","on")
    skip_mutations = os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "true").lower() in ("1","true","yes","on")
    return {
        "ok": True,
        "execute_trades": execute_trades,
        "skip_mutations": skip_mutations,
    }



