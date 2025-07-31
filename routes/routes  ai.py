# routes/ai.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from utils.ai_analysis import analyze_with_ai, predict_optimal_sl_tp

router = APIRouter()

class AIAnalysisRequest(BaseModel):
    rsi: float
    adx: float
    pattern: str = ""
    trend: str = ""
    volume: float = 0

class PredictSLTPRequest(BaseModel):
    symbol: str
    entry_price: float
    direction: str  # "LONG" or "SHORT"

@router.post("/ai-analyze", tags=["AI"])
def ai_analysis(request: AIAnalysisRequest):
    try:
        result = analyze_with_ai(
            rsi=request.rsi,
            adx=request.adx,
            pattern=request.pattern,
            trend=request.trend,
            volume=request.volume
        )
        return {"analysis": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI analysis error: {e}")

@router.post("/predict-sl-tp", tags=["AI"])
def predict_sl_tp(request: PredictSLTPRequest):
    try:
        result = predict_optimal_sl_tp(
            direction=request.direction,
            entry=request.entry_price  # 🔧 שם נכון לפי ai_analysis.py
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SL/TP prediction error: {e}")



