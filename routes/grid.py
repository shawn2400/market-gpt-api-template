# routes/grid.py
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List

from utils.auth import require_api_key
from utils.account_router import get_account_credentials
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
    side: str = Field(..., pattern="^(LONG|SHORT|BUY|SELL)$", example="LONG")  # fixed regex→pattern
    budget: float = Field(..., gt=0, example=100)
    leverage: int = Field(10, ge=1, le=125, example=10)
    grids: int = Field(3, ge=1, le=20, example=3)
    dry_run: bool = Field(True, description="אם True → לא מציב פקודות אמיתיות")
    market: str = Field("futures", pattern="^(futures|spot)$", example="futures")  # fixed regex→pattern
    account_id: str = Field("main", description="ID מה־accounts_config.json")

class GridTradeResponse(BaseModel):
    ok: bool
    mode: str
    symbol: str
    side: str
    market: str
    account_id: str
    base_price: Optional[float]
    budget: float
    leverage: Optional[int] = None
    levels: Optional[List[float]] = None
    allocations: Optional[List[float]] = None
    orders: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None

# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────
@router.get("/status")
def grid_status() -> Dict[str, Any]:
    return {"ok": True, "grid_enabled": True, "note": "Grid engine ready"}

@router.get("/active")
def grid_active() -> Dict[str, Any]:
    return {"ok": True, "active": []}

@router.post("/trade", response_model=GridTradeResponse)
async def trade_grid(req: GridTradeRequest):
    sym = req.symbol.upper().strip()
    market = req.market.lower().strip()
    acc_id = req.account_id.strip()

    creds = get_account_credentials(acc_id)
    if not creds:
        raise HTTPException(status_code=400, detail=f"Account {acc_id} not found in accounts_config.json")

    try:
        if market == "spot":
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
                "account_id": acc_id,
                "base_price": price,
                "budget": req.budget,
                "levels": res.get("grid_levels"),
                "allocations": None,
                "orders": [],
                "error": res.get("error"),
            }

        elif market == "futures":
            price = futures_mark_price(sym)
            if not price:
                raise RuntimeError("Futures mark price unavailable")

            if req.dry_run:
                res = basic_grid(sym, levels=req.grids)
                return {
                    "ok": bool(res.get("ok")),
                    "mode": "futures_dry",
                    "symbol": sym,
                    "side": req.side,
                    "market": "futures",
                    "account_id": acc_id,
                    "base_price": price,
                    "budget": req.budget,
                    "leverage": req.leverage,
                    "levels": res.get("grid_levels"),
                    "allocations": None,
                    "orders": [],
                    "error": res.get("error"),
                }
            else:
                res = await start_grid_for_position(sym)
                return {
                    "ok": bool(res.get("ok")),
                    "mode": "futures_live",
                    "symbol": sym,
                    "side": req.side,
                    "market": "futures",
                    "account_id": acc_id,
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


















