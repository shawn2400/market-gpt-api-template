# routes/trade.py
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

# --- Auth wrapper ---
try:
    from utils.auth import require_bearer_token as _raw_require_bearer
    def require_bearer_token(authorization: Optional[str] = Header(default=None)):
        return _raw_require_bearer(authorization=authorization)
except Exception:
    def require_bearer_token(authorization: Optional[str] = Header(default=None)):
        return None

router = APIRouter(prefix="/trade", tags=["Trades"], dependencies=[Depends(require_bearer_token)])


# --- Models ---
class TradeRequest(BaseModel):
    symbol: str
    side: str  # LONG / SHORT
    entry: float
    sl: Optional[float] = None
    tp: Optional[float] = None
    leverage: Optional[int] = 5
    budget: Optional[float] = 50


class TradeResponse(BaseModel):
    ok: bool
    trade_id: str
    symbol: str
    side: str
    entry: float
    sl: Optional[float]
    tp: Optional[float]
    leverage: int
    budget: float
    status: str


# --- Endpoints ---
@router.post("/", response_model=TradeResponse, summary="Open new trade", operation_id="postOpenTrade")
async def open_trade(req: TradeRequest):
    """
    פותח טרייד חדש ב־AlgoGPT.
    """
    # כאן נכנס הלוגיקה האמיתית מול Binance / DB
    trade_id = f"TRD-{req.symbol}-{req.side}-001"
    return TradeResponse(
        ok=True,
        trade_id=trade_id,
        symbol=req.symbol.upper(),
        side=req.side.upper(),
        entry=req.entry,
        sl=req.sl,
        tp=req.tp,
        leverage=req.leverage or 5,
        budget=req.budget or 50,
        status="OPEN",
    )


@router.get("/{trade_id}", response_model=TradeResponse, summary="Get trade status", operation_id="getTradeStatus")
async def get_trade(trade_id: str):
    """
    מחזיר מצב נוכחי של טרייד לפי מזהה.
    """
    # דמה בלבד – במציאות יגיע מ־DB
    return TradeResponse(
        ok=True,
        trade_id=trade_id,
        symbol="BTCUSDT",
        side="LONG",
        entry=42000,
        sl=41500,
        tp=44000,
        leverage=10,
        budget=100,
        status="OPEN",
    )


@router.delete("/{trade_id}", summary="Close trade", operation_id="deleteTrade")
async def close_trade(trade_id: str):
    """
    סוגר טרייד קיים.
    """
    return {"ok": True, "trade_id": trade_id, "status": "CLOSED"}




































































































































































































































































































































































































































































































































































































































