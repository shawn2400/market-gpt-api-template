# routes/trade.py
from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from utils.auth import require_api_key
from utils.trade_executor import execute_trade_live
from utils.account_router import get_account_credentials

logger = logging.getLogger("algogpt.routes.trade")

router = APIRouter(
    prefix="/trade",
    tags=["Trade"],
    dependencies=[Depends(require_api_key)],
)


# ──────────────────────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────────────────────
class TradeRequest(BaseModel):
    symbol: str = Field(..., description="Trading pair (e.g. BTCUSDT)")
    side: str = Field(..., description="LONG/SHORT or BUY/SELL")
    budget: float = Field(..., description="Budget in USDT")
    leverage: int = Field(..., description="Leverage (1–125)")
    entry: Optional[float] = Field(None, description="Entry price (default=mark price)")
    sl: float = Field(..., description="Stop-loss price")
    tp: float = Field(..., description="Take-profit price")
    dry_run: bool = Field(True, description="Dry-run only (default true)")
    quantity: Optional[float] = Field(None, description="Force quantity override")
    account_id: Optional[str] = Field("main", description="Account ID from accounts_config.json")


class TradeResponse(BaseModel):
    ok: bool
    mode: str
    symbol: str
    side: str
    entry: float
    sl: float
    tp: float
    leverage: int
    budget: float
    quantity: Optional[float] = None
    order: Optional[dict] = None
    error: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/execute", response_model=TradeResponse)
async def execute_trade(req: TradeRequest):
    """Execute trade (supports multi-account via account_id)."""

    # 1) קבלת חשבון
    creds = get_account_credentials(req.account_id or "main")
    if not creds:
        raise HTTPException(status_code=404, detail=f"Account '{req.account_id}' not found")

    # ⚠️ בעתיד: כאן אפשר להחליף את api_key/api_secret דינמית לפי creds

    logger.info({
        "event": "trade_execute_request",
        "account": req.account_id,
        "symbol": req.symbol,
        "side": req.side,
        "budget": req.budget,
        "leverage": req.leverage,
    })

    # 2) קריאה ל־executor
    result = await execute_trade_live(
        symbol=req.symbol,
        side=req.side,
        budget=req.budget,
        leverage=req.leverage,
        entry=req.entry,
        sl=req.sl,
        tp=req.tp,
        dry_run=req.dry_run,
        quantity=req.quantity,
    )

    return result




















































































































































































































































































































































































































































































































































































































































