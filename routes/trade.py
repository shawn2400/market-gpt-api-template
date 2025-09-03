# routes/trade.py
from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from utils.auth import require_api_key
from utils.trade_executor import execute_trade_live
from utils.grid_executor import execute_grid_trade
from utils.account_router import get_account_credentials
from utils import binance_client, binance_spot_client

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
    leverage: int = Field(..., description="Leverage (1–125, ignored in spot)")
    entry: Optional[float] = Field(None, description="Entry price (default=mark/spot price)")
    sl: float = Field(..., description="Stop-loss price")
    tp: float = Field(..., description="Take-profit price")
    dry_run: bool = Field(True, description="Dry-run only (default true)")
    quantity: Optional[float] = Field(None, description="Force quantity override")
    account_id: Optional[str] = Field("main", description="Account ID from accounts_config.json")


class GridTradeRequest(BaseModel):
    symbol: str
    side: str
    budget: float
    leverage: int = 10
    grids: int = 3
    atr_mults: list[float] = Field(default=[1.0, 1.8, 2.6])
    account_id: Optional[str] = "main"
    dry_run: bool = True


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
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _select_client(market: str):
    if market.lower() == "spot":
        return binance_spot_client
    return binance_client


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/execute", response_model=TradeResponse)
async def execute_trade(req: TradeRequest):
    """Execute trade (multi-account, supports spot + futures)."""

    # 1) Fetch account
    creds = get_account_credentials(req.account_id or "main")
    if not creds:
        raise HTTPException(status_code=404, detail=f"Account '{req.account_id}' not found")

    market = creds.get("market", "futures")
    client = _select_client(market)

    logger.info({
        "event": "trade_execute_request",
        "account": req.account_id,
        "market": market,
        "symbol": req.symbol,
        "side": req.side,
        "budget": req.budget,
        "leverage": req.leverage,
    })

    # 2) Futures → השתמש ב־execute_trade_live
    if market.lower() == "futures":
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

    # 3) Spot → רק סימולציה / ביצוע פשוט
    if market.lower() == "spot":
        px = client.spot_price(req.symbol)
        if not px:
            raise HTTPException(status_code=400, detail=f"Spot price not available for {req.symbol}")

        return {
            "mode": "spot",
            "ok": True,
            "symbol": req.symbol.upper(),
            "side": req.side.upper(),
            "entry": float(px),
            "sl": float(req.sl),
            "tp": float(req.tp),
            "leverage": 1,
            "budget": float(req.budget),
            "quantity": float(req.budget) / float(px),
        }

    raise HTTPException(status_code=400, detail=f"Unsupported market '{market}'")


@router.post("/grid")
async def execute_grid(req: GridTradeRequest):
    """Execute grid trade (multi-account, futures only)."""

    creds = get_account_credentials(req.account_id or "main")
    if not creds:
        raise HTTPException(status_code=404, detail=f"Account '{req.account_id}' not found")

    if creds.get("market", "futures").lower() != "futures":
        raise HTTPException(status_code=400, detail="Grid trading supported only on Futures")

    result = await execute_grid_trade(
        symbol=req.symbol,
        side=req.side,
        budget=req.budget,
        leverage=req.leverage,
        grids=req.grids,
        atr_mults=req.atr_mults,
        dry_run=req.dry_run,
    )

    return result





















































































































































































































































































































































































































































































































































































































































