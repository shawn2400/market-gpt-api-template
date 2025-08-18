# routes/news.py
from __future__ import annotations
from fastapi import APIRouter, Query

router = APIRouter(prefix="/news", tags=["News"])

@router.get("", operation_id="getNewsAlias")
async def get_news_alias(filter: str | None = Query(None)):
    return await get_crypto_news(filter)

@router.get("/crypto", operation_id="getCryptoNews")
async def get_crypto_news(filter: str | None = Query(None)):
    # אפשר להחליף בחיבור אמיתי ל-CryptoPanic/NewsAPI בהמשך
    return {"ok": True, "count": 0, "items": [], "note": "news provider not configured"}








