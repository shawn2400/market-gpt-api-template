# routes/news.py
from __future__ import annotations
from typing import Dict, Any
from fastapi import APIRouter, Depends, Query
import asyncio, os

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

from utils.cache import aget_or_set
from utils.news_utils import fetch_crypto_news, analyze_news_impact

TTL_NEWS = float(os.getenv("CACHE_TTL_NEWS", "120"))  # 2m

router = APIRouter(prefix="/news", tags=["News"], dependencies=[Depends(require_bearer_token)])

@router.get("/crypto", summary="Crypto news (CryptoPanic) with impact score", operation_id="getCryptoNews")
async def get_crypto_news(filter: str | None = Query(None)) -> Dict[str, Any]:
    key = f"news|{filter or ''}"
    async def load():
        news = await asyncio.to_thread(fetch_crypto_news, True, filter or "")
        scored = await asyncio.to_thread(analyze_news_impact, news)
        return {"ok": True, "count": len(scored), "items": scored}
    return await aget_or_set(key, TTL_NEWS, load)


