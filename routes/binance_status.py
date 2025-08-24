# routes/binance_status.py
from __future__ import annotations
from fastapi import APIRouter, Depends
from utils.auth import require_api_key
from utils.binance_client import binance_http_status

router = APIRouter(tags=["Binance"], dependencies=[Depends(require_api_key)])

@router.get("/status", summary="Binance HTTP/Circuit status")
async def binance_status():
    """
    סטטוס קליל: הוסט האחרון, האם ה־Circuit Breaker פתוח,
    זמן קירור נותר, ושגיאה אחרונה (אם יש). ללא פניות רשת חיצוניות.
    """
    return binance_http_status()
