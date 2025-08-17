from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from utils.auth import require_bearer_token
from utils.ai_analysis import predict_optimal_sl_tp

router = APIRouter()

class SLTPRequest(BaseModel):
    symbol: str
    direction: str  # LONG or SHORT
    entry: float

@router.post("/sltp")
async def get_sltp(data: SLTPRequest, request: Request = Depends(require_bearer_token)):
    sl, tp = await predict_optimal_sl_tp(data.symbol, data.direction, data.entry)
    return {
        "symbol": data.symbol,
        "direction": data.direction,
        "entry": data.entry,
        "sl": sl,
        "tp": tp
    }






