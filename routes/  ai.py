# routes/ai.py
from fastapi import APIRouter
from pydantic import BaseModel
from utils.ai_analysis import analyze_with_ai

router = APIRouter()

class AIAnalysisRequest(BaseModel):
    symbol: str
    rsi: float
    adx: float
    trend: str
    pattern: str
    volume: float

@router.post("/ai-analyze")
async def ai_analyze(data: AIAnalysisRequest):
    try:
        result = analyze_with_ai(
            symbol=data.symbol,
            rsi=data.rsi,
            adx=data.adx,
            trend=data.trend,
            pattern=data.pattern,
            volume=data.volume
        )
        return {"analysis": result}
    except Exception as e:
        return {"error": str(e)}





