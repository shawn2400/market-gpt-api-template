from fastapi import APIRouter, Request
from utils.ai_analysis import analyze_with_ai

router = APIRouter()


@router.post("/ai-analyze")
async def ai_analyze(request: Request):
    try:
        data = await request.json()
        result = analyze_with_ai(data)
        return result
    except Exception as e:
        return {"error": str(e)}


