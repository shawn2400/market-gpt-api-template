# routes/ai.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from utils.ai_analysis import analyze_with_ai, predict_optimal_sl_tp

router = APIRouter(tags=["AI"])

class AnalyzeRequest(BaseModel):
    rsi: float
    adx: float
    volume: float
    pattern: str = ""
    trend: str = ""

class PredictSLTPRequest(BaseModel):
    entry_price: float
    direction: str

@router.post("/analyze")
async def ai_analyze(request: AnalyzeRequest):
    try:
        result = analyze_with_ai(
            rsi=request.rsi,
            adx=request.adx,
            volume=request.volume,
            pattern=request.pattern,
            trend=request.trend
        )
        return {"analysis": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/predict-sl-tp")
async def ai_predict_sl_tp(request: PredictSLTPRequest):
    try:
        result = predict_optimal_sl_tp(
            direction=request.direction,
            entry_price=request.entry_price
        )
        return {"predicted_sl_tp": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

