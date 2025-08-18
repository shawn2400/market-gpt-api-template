# routes/news.py
from __future__ import annotations
from fastapi import APIRouter, Query

router = APIRouter(prefix="/news", tags=["News"])

@router.get("/crypto", operation_id="getCryptoNews")
async def get_crypto_news(filter: str | None = Query(None)):
    try:
        # integration אמיתי אפשר להוסיף בהמשך; כעת מחזיר 200 בטוח
        return {"ok": False, "count": 0, "items": [], "note": "news provider not configured"}
    except Exception:
        return {"ok": False, "count": 0, "items": [], "note": "news error"}








