from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import logging

from utils.auth import require_bearer_token
from utils.ws_fallback import get_price
from utils.ai_analysis import analyze_with_ai, predict_optimal_sl_tp
from utils.binance_trader import binance_futures_trade

logger = logging.getLogger(__name__)
router = APIRouter()

# ✅ מודל בקשת טרייד
class TradeRequest(BaseModel):
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry: Optional[float] = None
    quantity: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None

# 📈 מחזיר מחיר נוכחי מהמערכת
@router.get("/price")
async def get_price_endpoint(symbol: str):
    try:
        price = await get_price(symbol)
        return {"symbol": symbol, "price": price}
    except Exception as e:
        logger.error(f"[Price] Failed to fetch price for {symbol}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch price")

# 🤖 ניתוח סימבול עם GPT
@router.post("/ai/analyze")
async def ai_analyze(indicators: dict, token=Depends(require_bearer_token)):
    try:
        result = await analyze_with_ai(indicators)
        return result
    except Exception as e:
        logger.error(f"[AI Analyze] Error: {e}")
        raise HTTPException(status_code=500, detail="AI analysis failed")

# 🤖 חיזוי SL/TP עם GPT
@router.post("/sltp")
async def predict_sltp(req: TradeRequest, token=Depends(require_bearer_token)):
    if not req.symbol or not req.side or not req.entry:
        raise HTTPException(status_code=400, detail="Missing required fields")
    try:
        sl, tp = await predict_optimal_sl_tp(req.symbol, req.side, req.entry)
        return {"symbol": req.symbol, "sl": sl, "tp": tp}
    except Exception as e:
        logger.error(f"[SLTP Predict] Error: {e}")
        raise HTTPException(status_code=500, detail="SL/TP prediction failed")

# ✅ מבצע טרייד בפועל
@router.post("/execute-trade")
async def execute_trade(req: TradeRequest, token=Depends(require_bearer_token)):
    try:
        if not req.entry:
            req.entry = await get_price(req.symbol)
        result = await binance_futures_trade(
            symbol=req.symbol,
            side=req.side,
            entry=req.entry,
            quantity=req.quantity,
            sl=req.sl,
            tp=req.tp
        )
        return result
    except Exception as e:
        logger.error(f"[Trade] Execution failed: {e}")
        raise HTTPException(status_code=500, detail="Trade execution failed")





