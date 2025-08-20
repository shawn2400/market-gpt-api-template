# routes/trade.py
from __future__ import annotations
import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field, constr

from utils import sltp

logger = logging.getLogger("trade")

router = APIRouter(prefix="/trade", tags=["Trading"])

# ---------- Models ----------
class TradeRequest(BaseModel):
    symbol: constr(strip_whitespace=True, to_upper=True) = Field(..., example="BTCUSDT")
    side: constr(strip_whitespace=True, to_upper=True) = Field(..., description="LONG or SHORT")
    type: constr(strip_whitespace=True, to_upper=True) = Field(..., description="LIMIT or STOP_LIMIT")
    price: float = Field(..., gt=0, description="Entry price")
    quantity: float = Field(..., gt=0, description="Order quantity")
    entry: Optional[float] = Field(None, description="Entry price (required if auto-calculating SL/TP)")
    sl: Optional[float] = Field(None, description="Stop loss")
    tp: Optional[float] = Field(None, description="Take profit")
    dry_run: bool = Field(False, description="Simulate order without sending to exchange")

class TradeResponse(BaseModel):
    ok: bool
    executed: bool
    dry_run: bool
    details: Dict[str, Any]

# ---------- Routes ----------
@router.post("/execute", response_model=TradeResponse)
async def execute_trade(req: TradeRequest = Body(...)) -> TradeResponse:
    """
    Execute (or dry-run) a trade.
    Supported: LONG/SHORT + LIMIT/STOP_LIMIT
    """

    # --- Validation ---
    side = req.side.upper()
    if side not in ("LONG", "SHORT"):
        return TradeResponse(ok=False, executed=False, dry_run=req.dry_run,
                             details={"error": f"Invalid side: {req.side}. Use LONG or SHORT"})

    if req.type not in ("LIMIT", "STOP_LIMIT"):
        return TradeResponse(ok=False, executed=False, dry_run=req.dry_run,
                             details={"error": f"Invalid type: {req.type}. Use LIMIT or STOP_LIMIT"})

    # Require entry if SL/TP requested
    if (req.sl or req.tp) and not req.entry:
        return TradeResponse(
            ok=False, executed=False, dry_run=req.dry_run,
            details={"error": "entry is required when auto-calculating SL/TP"}
        )

    # --- SL/TP logic ---
    sl_price, tp_price = None, None
    if req.sl or req.tp:
        sl_price, tp_price = sltp.calc_sl_tp(entry=req.entry or req.price,
                                             side=side,
                                             sl=req.sl,
                                             tp=req.tp)

    # --- Dry run ---
    if req.dry_run:
        return TradeResponse(
            ok=True, executed=False, dry_run=True,
            details={
                "symbol": req.symbol,
                "side": side,
                "type": req.type,
                "price": req.price,
                "quantity": req.quantity,
                "sl": sl_price,
                "tp": tp_price,
                "note": "dry-run only"
            }
        )

    # --- Live order (placeholder, connect to Binance API here) ---
    try:
        # TODO: integrate with Binance (spot/futures) via utils/binance_client
        logger.info(f"Executing {side} {req.symbol} {req.quantity} @ {req.price} ({req.type})")

        # Simulate success
        return TradeResponse(
            ok=True, executed=True, dry_run=False,
            details={
                "symbol": req.symbol,
                "side": side,
                "type": req.type,
                "price": req.price,
                "quantity": req.quantity,
                "sl": sl_price,
                "tp": tp_price,
                "exchange_order_id": "SIM123456"
            }
        )
    except Exception as e:
        logger.exception("Trade execution failed")
        return TradeResponse(
            ok=False, executed=False, dry_run=False,
            details={"error": str(e)}
        )


















































































































































































































































































































