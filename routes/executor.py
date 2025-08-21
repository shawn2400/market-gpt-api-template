# routes/executor.py
from __future__ import annotations
from typing import Optional, List
from fastapi import APIRouter, Depends
from pydantic import BaseModel

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

from utils.auto_executor import (
    is_executor_running,
    start_executor,
    stop_executor,
    EXECUTOR_SYMBOLS,   # 🆕 מייבא את הרשימה הפעילה
)
from utils.watchlist_utils import load_watchlist


router = APIRouter(tags=["Executor"], dependencies=[Depends(require_bearer_token)])


class ExecutorStatus(BaseModel):
    ok: bool = True
    running: bool


class ExecutorActionResponse(BaseModel):
    ok: bool
    status: Optional[str] = None
    error: Optional[str] = None


class ExecutorSymbolsResponse(BaseModel):
    ok: bool = True
    count: int
    symbols: List[str]


@router.get("/executor/status", response_model=ExecutorStatus)
def executor_status() -> ExecutorStatus:
    running = bool(is_executor_running())
    return ExecutorStatus(ok=True, running=running)


@router.post("/executor/start", response_model=ExecutorActionResponse)
async def executor_start() -> ExecutorActionResponse:
    try:
        if is_executor_running():
            return ExecutorActionResponse(ok=True, status="already_running")
        start_executor()
        return ExecutorActionResponse(ok=True, status="started")
    except Exception as e:
        return ExecutorActionResponse(ok=False, error=str(e))


@router.post("/executor/stop", response_model=ExecutorActionResponse)
async def executor_stop() -> ExecutorActionResponse:
    try:
        if not is_executor_running():
            return ExecutorActionResponse(ok=True, status="already_stopped")
        stop_executor()
        return ExecutorActionResponse(ok=True, status="stopped")
    except Exception as e:
        return ExecutorActionResponse(ok=False, error=str(e))


@router.get("/executor/symbols", response_model=ExecutorSymbolsResponse)
def executor_symbols() -> ExecutorSymbolsResponse:
    """
    מחזיר את רשימת הסימבולים שה־Auto Executor באמת סורק כרגע (LIVE).
    """
    if EXECUTOR_SYMBOLS:
        symbols = EXECUTOR_SYMBOLS
    else:
        # fallback אם לא רץ
        watchlist = load_watchlist()
        symbols = [it["symbol"].upper() for it in watchlist]
        if "BTCUSDT" not in symbols:
            symbols.insert(0, "BTCUSDT")

    return ExecutorSymbolsResponse(ok=True, count=len(symbols), symbols=symbols)








