# routes/grid.py
from __future__ import annotations
from fastapi import APIRouter, Query
from typing import Dict, Any, List
import logging

from utils.binance_client import grid_orders, futures_new_order

router = APIRouter(prefix="/grid", tags=["Grid Trading"])
logger = logging.getLogger("algogpt.grid")

# סטטוס פנימי לניהול גריד
_GRID_STATUS: Dict[str, Any] = {
    "active": False,
    "symbol": None,
    "orders": [],
    "params": {},
}

@router.get("/status", summary="Get Grid Status")
async def grid_status() -> Dict[str, Any]:
    return {"ok": True, "status": _GRID_STATUS}

@router.post("/start", summary="Start Grid")
async def grid_start(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    side: str = Query(..., description="BUY or SELL"),
    start_price: float = Query(..., description="Start price for grid"),
    end_price: float = Query(..., description="End price for grid"),
    steps: int = Query(..., ge=2, le=50, description="Number of grid steps"),
    qty: float = Query(..., description="Quantity per order"),
    dry_run: bool = Query(True, description="If true, don’t send real orders")
) -> Dict[str, Any]:
    try:
        orders = grid_orders(symbol, side, start_price, end_price, steps, qty)
        _GRID_STATUS.update({
            "active": True,
            "symbol": symbol,
            "params": {
                "side": side,
                "start_price": start_price,
                "end_price": end_price,
                "steps": steps,
                "qty": qty,
                "dry_run": dry_run,
            },
            "orders": orders,
        })

        if not dry_run:
            executed: List[Dict[str, Any]] = []
            for o in orders:
                try:
                    order = futures_new_order(
                        symbol=o["symbol"],
                        side=o["side"],
                        type=o["type"],
                        quantity=o["quantity"],
                        price=o["price"],
                        timeInForce=o["timeInForce"],
                    )
                    executed.append(order)
                except Exception as ex:
                    logger.warning(f"Failed to place grid order {o}: {ex}")
            return {"ok": True, "executed": executed, "status": _GRID_STATUS}

        return {"ok": True, "orders": orders, "status": _GRID_STATUS}
    except Exception as e:
        logger.exception("Grid start failed")
        return {"ok": False, "error": str(e)}

@router.post("/stop", summary="Stop Grid")
async def grid_stop() -> Dict[str, Any]:
    _GRID_STATUS.update({"active": False})
    return {"ok": True, "status": _GRID_STATUS}












