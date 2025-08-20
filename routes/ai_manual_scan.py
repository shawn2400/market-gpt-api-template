# routes/ai_manual_scan.py
from fastapi import APIRouter, Query, HTTPException, status
from fastapi.responses import JSONResponse
from utils.ai_client import ai_client

router = APIRouter()

@router.get("/ai/manual-scan")
async def ai_manual_scan(symbol: str = Query(None, description="Crypto symbol, e.g. BTCUSDT")):
    """
    סריקה ידנית עם AI.
    חובה לשלוח ?symbol=BTCUSDT אחרת מחזיר שגיאה ברורה.
    """
    if not symbol:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "error": "Missing required parameter: symbol (?symbol=BTCUSDT)"}
        )

    try:
        prompt = f"Analyze trading opportunities for {symbol} in crypto futures."
        reply = await ai_client.chat(prompt, system="Be concise, structured, and technical.", max_tokens=300)

        return JSONResponse(
            content={
                "ok": True,
                "symbol": symbol,
                "analysis": reply.strip()
            },
            status_code=200
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"ok": False, "error": str(e)}
        )
