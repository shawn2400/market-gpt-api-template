# routes/ai_manual_scan.py
import logging
from fastapi import APIRouter, Query, HTTPException
from utils.ai_client import ai_client

router = APIRouter()

@router.get("/ai/manual-scan")
async def manual_scan(
    symbol: str = Query(..., description="Symbol to scan, e.g. BTCUSDT"),
    interval: str = Query("15m", description="Interval (e.g. 1m, 5m, 15m, 1h)"),
):
    """
    הרצה ידנית של סריקה עם AI למטבע מסוים.
    מחזיר טקסט ניתוח מהמודל + סטטוס.
    """
    try:
        prompt = f"Analyze {symbol} on {interval} interval. Provide key technical signals and trading insight."
        result = await ai_client.chat(
            prompt,
            system="Be concise. Focus only on technical signals, trend, and possible entry/exit.",
            max_tokens=300,
        )

        if not result:
            raise HTTPException(status_code=503, detail="AI returned empty response")

        return {
            "ok": True,
            "symbol": symbol,
            "interval": interval,
            "analysis": result.strip(),
        }
    except Exception as e:
        logging.exception("manual_scan failed")
        raise HTTPException(status_code=500, detail=str(e))
