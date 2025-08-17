# routes/news.py
from __future__ import annotations
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, Query

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token(): return None

from utils.news_utils import fetch_crypto_news, analyze_news_impact

router = APIRouter(prefix="/news", tags=["News"], dependencies=[Depends(require_bearer_token)])

@router.get("/crypto", summary="Crypto news (CryptoPanic) with impact score", operation_id="getCryptoNews")
async def get_crypto_news(filter: Optional[str] = Query(None)) -> Dict[str, Any]:
    raw = fetch_crypto_news(public=True, filter_=filter or "")
    items = analyze_news_impact(raw)
    return {"ok": True, "count": len(items), "items": items}
