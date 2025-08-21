# routes/executor.py
from __future__ import annotations
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from datetime import datetime, timezone

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

from utils.auto_executor import (
    is_executor_running,
    start_executor,
    stop_executor,
    EXECUTOR_SYMBOLS,
    EXECUTOR_LAST_TS,
    EXECUTOR_LOGS,
    EXECUTOR_TRADES,
)
from utils.watchlist_utils import load_watchlist
from utils.binance_client import futures_open_positions
from utils.binance_trader import force_close_position

router = APIRouter(tags=["Executor"], dependencies=[Depends(require_bearer_token)])

# =====================
# Models
# =====================
class ExecutorStatus(BaseModel):
    ok: bool = True
    running: bool
    last_ts: Optional[str] = None

class ExecutorActionResponse(BaseModel):
    ok: bool
    status: Optional[str] = None
    error: Optional[str] = None

class ExecutorSymbolsResponse(BaseModel):
    ok: bool = True
    count: int
    symbols: List[str]
    last_ts: Optional[str] = None

class ExecutorLogsResponse(BaseModel):
    ok: bool = True
    count: int
    logs: List[dict]

class ExecutorTradesResponse(BaseModel):
    ok: bool = True
    count: int
    trades: List[dict]

class ExecutorPositionsResponse(BaseModel):
    ok: bool = True
    count: int
    positions: List[dict]
    error: Optional[str] = None

# =====================
# Endpoints
# =====================
@router.get("/executor/status", response_model=ExecutorStatus)
def executor_status() -> ExecutorStatus:
    running = bool(is_executor_running())
    last_ts = (
        datetime.fromtimestamp(EXECUTOR_LAST_TS, tz=timezone.utc).isoformat()
        if EXECUTOR_LAST_TS
        else None
    )
    return ExecutorStatus(ok=True, running=running, last_ts=last_ts)

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
    if EXECUTOR_SYMBOLS:
        symbols = EXECUTOR_SYMBOLS
    else:
        watchlist = load_watchlist()
        symbols = [it["symbol"].upper() for it in watchlist]
        if "BTCUSDT" not in symbols:
            symbols.insert(0, "BTCUSDT")

    last_ts = (
        datetime.fromtimestamp(EXECUTOR_LAST_TS, tz=timezone.utc).isoformat()
        if EXECUTOR_LAST_TS
        else None
    )

    return ExecutorSymbolsResponse(ok=True, count=len(symbols), symbols=symbols, last_ts=last_ts)

@router.get("/executor/logs", response_model=ExecutorLogsResponse)
def executor_logs(limit: int = Query(50, ge=1, le=200)) -> ExecutorLogsResponse:
    logs = list(EXECUTOR_LOGS)[-limit:]
    return ExecutorLogsResponse(ok=True, count=len(logs), logs=logs)

@router.get("/executor/trades", response_model=ExecutorTradesResponse)
def executor_trades(limit: int = Query(50, ge=1, le=200)) -> ExecutorTradesResponse:
    trades = list(EXECUTOR_TRADES)[-limit:]
    return ExecutorTradesResponse(ok=True, count=len(trades), trades=trades)

@router.get("/executor/open_positions", response_model=ExecutorPositionsResponse)
def executor_open_positions() -> ExecutorPositionsResponse:
    try:
        positions = futures_open_positions()
        return ExecutorPositionsResponse(ok=True, count=len(positions), positions=positions)
    except Exception as e:
        return ExecutorPositionsResponse(ok=False, count=0, positions=[], error=str(e))

# 🔴 NEW: Force Close Endpoint
@router.post("/executor/force_close", response_model=dict)
def executor_force_close(symbol: str):
    """
    סוגר בכוח פוזיציה פתוחה בסימבול מסוים.
    """
    return force_close_position(symbol)













