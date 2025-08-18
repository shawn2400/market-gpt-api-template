# routes/news.py
from __future__ import annotations
from fastapi import APIRouter, Query

router = APIRouter(prefix="/news", tags=["News"])  # ללא Depends/Bearer

@router.get("/crypto", operation_id="getCryptoNews")
async def get_crypto_news(filter: str | None = Query(None)):
    try:
        # from utils.news_providers import cryptopanic_fetch
        # items = cryptopanic_fetch(filter=filter)
        # return {"ok": True, "count": len(items), "items": items}
        return {"ok": False, "count": 0, "items": [], "note": "news provider not configured"}
    except Exception:
        return {"ok": False, "count": 0, "items": [], "note": "news error"}







