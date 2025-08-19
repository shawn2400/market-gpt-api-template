# routes/news.py
from __future__ import annotations
import os
import time
from typing import List, Optional, Dict, Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import requests

router = APIRouter(tags=["News"])  # ציבורי

class NewsItem(BaseModel):
    title: str
    url: str
    published_at: Optional[str] = None
    impact_score: int = 0
    source: Optional[Dict[str, Any]] = None
    currencies: Optional[List[Dict[str, Any]]] = None

class NewsResponse(BaseModel):
    ok: bool = True
    count: int = 0
    items: List[NewsItem] = Field(default_factory=list)

def _fetch_cryptopanic() -> List[NewsItem]:
    token = (os.getenv("CRYPTOPANIC_TOKEN") or "").strip()
    if not token:
        return []
    url = "https://cryptopanic.com/api/v1/posts/"
    params = {
        "auth": token,
        "public": "true",
        "currencies": "BTC,ETH",
        "filter": "rising",
    }
    try:
        r = requests.get(url, params=params, timeout=6)
        r.raise_for_status()
        data = r.json() or {}
        results = data.get("results") or []
        out: List[NewsItem] = []
        for it in results[:30]:
            try:
                out.append(NewsItem(
                    title=it.get("title") or "",
                    url=it.get("url") or it.get("domain") or "",
                    published_at=it.get("published_at"),
                    impact_score=int(it.get("votes", {}).get("total", 0) or 0),
                    source={"domain": it.get("domain")},
                    currencies=[{"code": c.get("code")} for c in (it.get("currencies") or [])],
                ))
            except Exception:
                continue
        return out
    except Exception:
        return []

@router.get("/news/crypto", response_model=NewsResponse, operation_id="getCryptoNews")
def get_crypto_news() -> NewsResponse:
    items = _fetch_cryptopanic()
    return NewsResponse(ok=True, count=len(items), items=items)

@router.get("/news", response_model=NewsResponse, operation_id="getNewsAlias")
def get_news_alias() -> NewsResponse:
    return get_crypto_news()









