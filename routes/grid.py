# routes/grid.py
from __future__ import annotations
from fastapi import APIRouter, Query
from typing import Dict, Any
import logging

from utils.grid_utils import execute_grid_trade
from utils.grid_tracker import add_grid, get_open_grids, remove_grid

router = APIRouter(prefix="/grid", tags=["Grid"])
logger = logging.getLogger("algogpt.grid")

# --- Status ---
@router.get("/status", summary="Get Grid Status")
async def grid_status() -> Dict[str, Any]:
    grids = get_open_grids()
    return {"ok": True, "count": len(grids), "grids": grids}

# --- Start Grid ---
@router.post("/start", summary="Start Grid Trading")
async def grid_start(
    symbol: str = Query(..., description="Trading pair, e.g. BTCUSDT"),
    budget_usd: float = Query(..., gt=0, description="Total budget in USD"),
    grid_count: int = Query(6, ge=2, le=50, description="Number of grid levels"),
    grid_pct: float = Query(0.4, gt=0, description="Step size between levels (%)"),
    leverage: int = Query(20, gt=0, description="Leverage (futures only)"),
    futures: bool = Query(True, description="Use Futures if true, Spot if false"),
    tp_pct: float = Query(1.5, gt=0, description="TP per level (%)"),
    sl_pct: float = Query(1.0, gt=0, description="SL per level (%)"),
) -> Dict[str, Any]:
    try:
        result = await execute_grid_trade(
            symbol=symbol,
            budget_usd=budget_usd,
            grid_count=grid_count,
            grid_pct=grid_pct,
            leverage=leverage,
            futures=futures,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
        )

        if result.get("status") in ("success", "dry_run"):
            add_grid(result["plan"])

        return result
    except Exception as e:
        logger.exception("❌ Grid start failed")
        return {"status": "error", "error": str(e)}

# --- Stop Grid ---
@router.post("/stop", summary="Stop Grid for Symbol")
async def grid_stop(symbol: str = Query(..., description="Symbol to stop")) -> Dict[str, Any]:
    try:
        remove_grid(symbol)
        return {"ok": True, "removed_symbol": symbol}
    except Exception as e:
        logger.exception("❌ Grid stop failed")
        return {"ok": False, "error": str(e)}












