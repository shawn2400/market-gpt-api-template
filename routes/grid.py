# routes/grid.py
from fastapi import APIRouter, HTTPException, Depends, Header, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from utils.grid_utils import execute_grid_trade
from utils import config as cfg

router = APIRouter(prefix="/grid", tags=["Grid"])

def auth_dep(
    authorization: str = Header(default=""),
    x_api_key: str = Header(default=""),
    token: str = Query(default="")
):
    expected = (getattr(cfg, "API_BEARER_TOKEN", "") or "").strip()
    bearer = ""
    if authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    if not bearer:
        bearer = (x_api_key or token or "").strip()
    if expected:
        if bearer != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")
    else:
        if not bearer:
            raise HTTPException(status_code=401, detail="Unauthorized")
    return True

class GridTradeRequest(BaseModel):
    symbol: str = Field(..., description="למשל BTCUSDT")
    budget: float = Field(..., gt=0, description="תקציב כולל ב-USDT")
    grid_count: int = Field(6, ge=2, le=50, description="מספר רמות רשת (>=2)")
    grid_pct: float = Field(0.4, gt=0, le=5, description="אחוז הפרדה בין רמות (0.4 = 0.4%)")
    leverage: int = Field(20, ge=1, le=125, description="מינוף (בשימוש ב-Futures)")
    futures: bool = Field(True, description="True=Futures, False=Spot")
    tp_pct: float = Field(1.5, gt=0, le=10, description="TP אחוזי לכל רמה")
    sl_pct: float = Field(1.0, gt=0, le=10, description="SL אחוזי לכל רמה")

class GridTradeResponse(BaseModel):
    status: str
    reason: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

@router.post("/trade", operation_id="executeGrid", response_model=GridTradeResponse, dependencies=[Depends(auth_dep)])
async def grid_trade(req: GridTradeRequest) -> GridTradeResponse:
    try:
        res = await execute_grid_trade(
            symbol=req.symbol,
            budget_usd=req.budget,
            grid_count=req.grid_count,
            grid_pct=req.grid_pct,
            leverage=req.leverage,
            futures=req.futures,
            tp_pct=req.tp_pct,
            sl_pct=req.sl_pct,
        )
        status = str(res.get("status"))
        if status in ("success", "dry_run"):
            return GridTradeResponse(**res)
        raise HTTPException(status_code=400, detail=res.get("error", "grid trade failed"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))











