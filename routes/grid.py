# routes/grid.py
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List

from utils.auth import require_api_key
from utils.grid_utils import execute_grid_trade as basic_grid
from utils.grid_manager import start_grid_for_position
from utils.binance_spot_client import spot_price
from utils.binance_client import futures_mark_price

logger = logging.getLogger("algogpt.routes.grid")

router = APIRouter(prefix="/grid", tags=["Grid"], dependencies=[Depends(require_api_key)])

# ──────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────
class GridTradeRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    side: str = Field(..., regex="^(LONG|SHORT|BUY|SELL)$", example="LONG")
    budget: float = Field(..., gt=0, example=100)
    leverage: int = Field(10, ge=1, le=125, example=10)
    grids: int = Field(3, ge=1, le=20, example=3)
    dry_run: bool = Field(True, description="אם True → לא מציב פקודות אמיתיות")
    market: str = Field("futures", regex="^(futures|spot)$", example="futures")

class GridTradeResponse(BaseModel):
    ok: bool
    mode: str
    symbol: str
    side: str
    market: str
    base_price: Optional[float]
    budget: float
    leverage: Optional[int] = None
    levels: Optional[List[float]] = None
    allocations: Optional[List[float]] = None
    orders: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None

# ──────────────────────────────────────────────────────────────
# Existing endpoints
# ──────────────────────────────────────────────────────────────
@router.get("/status")
def grid_status() -> Dict[str, Any]:
    return {"ok": True, "grid_enabled": True, "active_strategies": 0, "note": "Grid engine loaded"}

@router.get("/active")
def grid_active() -> Dict[str, Any]:
    return {"ok": True, "active": []}

@router.post("/start")
def grid_start() -> Dict[str, Any]:
    return {"ok": True, "message": "Grid start requested"}

@router.post("/stop")
def grid_stop() -> Dict[str, Any]:
    return {"ok": True, "message": "Grid stop requested"}

# ──────────────────────────────────────────────────────────────
# New: /trade/grid endpoint
# ──────────────────────────────────────────────────────────────
@router.post("/trade", response_model=GridTradeResponse)
async def trade_grid(req: GridTradeRequest):
    """
    🔹 Endpoint ייעודי להפעלת Grid:
    - market=futures → משתמש ב־grid_manager (SL/TP אמיתיים)
    - market=spot → משתמש ב־grid_utils (סימולציה בסיסית)
    """
    sym = req.symbol.upper().strip()
    market = req.market.lower().strip()

    try:
        if market == "spot":
            # Spot סימולציה בלבד
            price = spot_price(sym)
            if not price:
                raise RuntimeError("Spot price unavailable")
            res = basic_grid(sym, levels=req.grids)
            return {
                "ok": bool(res.get("ok")),
                "mode": "spot_dry" if req.dry_run else "spot_live",
                "symbol": sym,
                "side": req.side,
                "market": "spot",
                "base_price": price,
                "budget": req.budget,
                "levels": res.get("grid_levels"),
                "allocations": None,
                "orders": [],
                "error": res.get("error"),
            }

        elif market == "futures":
            # Futures grid עם SL/TP אמיתי
            price = futures_mark_price(sym)
            if not price:
                raise RuntimeError("Futures mark price unavailable")
            if req.dry_run:
                # הרצה יבשה
                res = basic_grid(sym, levels=req.grids)
                return {
                    "ok": bool(res.get("ok")),
                    "mode": "futures_dry",
                    "symbol": sym,
                    "side": req.side,
                    "market": "futures",
                    "base_price": price,
                    "budget": req.budget,
                    "leverage": req.leverage,
                    "levels": res.get("grid_levels"),
                    "allocations": None,
                    "orders": [],
                    "error": res.get("error"),
                }
            else:
                # Live grid עם הצמדת SL/TP דרך grid_manager
                res = await start_grid_for_position(sym)
                return {
                    "ok": bool(res.get("ok")),
                    "mode": "futures_live",
                    "symbol": sym,
                    "side": req.side,
                    "market": "futures",
                    "base_price": price,
                    "budget": req.budget,
                    "leverage": req.leverage,
                    "levels": None,
                    "allocations": None,
                    "orders": res.get("state", {}),
                    "error": None if res.get("ok") else str(res.get("errors")),
                }
        else:
            raise HTTPException(status_code=400, detail="Invalid market")

    except Exception as e:
        logger.exception("grid_trade_failed")
        raise HTTPException(status_code=500, detail=f"Grid trade failed: {e}")
















