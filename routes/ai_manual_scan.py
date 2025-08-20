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
    מחזיר ניתוח, ציון איכות והמלצה (Buy/Sell/Neutral).
    """
    try:
        prompt = f"""
        Analyze {symbol} on {interval} interval.
        1. Provide short technical analysis (trend, momentum, key signals).
        2. Suggest one of: Buy, Sell, or Neutral.
        3. Give a Quality Score between 0 and 10 for confidence level.
        
        Respond in JSON only, with keys:
        - analysis: string
        - recommendation: string (Buy/Sell/Neutral)
        - quality: number (0–10)
        """

        result = await ai_client.chat(
            prompt,
            system="You are a trading assistant. Output strictly valid JSON.",
            max_tokens=400,
        )

        if not result:
            raise HTTPException(status_code=503, detail="AI returned empty response")

        # ננסה לפרסר ל־JSON
        import json
        try:
            parsed = json.loads(result)
        except Exception:
            logging.warning("AI response was not valid JSON → returning raw text")
            parsed = {"analysis": result.strip(), "recommendation": "Neutral", "quality": 5}

        return {
            "ok": True,
            "symbol": symbol,
            "interval": interval,
            **parsed,
        }

    except Exception as e:
        logging.exception("manual_scan failed")
        raise HTTPException(status_code=500, detail=str(e))

