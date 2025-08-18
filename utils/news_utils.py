# routes/news.py
from __future__ import annotations
import asyncio, os
from typing import Any, Dict, Optional
from fastapi import APIRouter, Query

router = APIRouter(prefix="/news", tags=["News"])

@router.get("/crypto", summary="Crypto news (CryptoPanic) with impact score", operation_id="getCryptoNews")
async def get_crypto_news(filter: Optional[str] = Query(None)) -> Dict[str, Any]:
    """
    תמיד 200. אם אין API Key/ספק – מחזיר feed ריק + note (לא 401).
    """
    api_key = os.getenv("CRYPTO_PANIC_API_KEY", "") or os.getenv("CRYPTOPANIC_API_KEY", "")

    try:
        from utils.news_utils import get_crypto_news as _provider  # type: ignore
    except Exception:
        _provider = None  # type: ignore

    if _provider:
        try:
            data = await asyncio.to_thread(_provider, filter)  # type: ignore
            if isinstance(data, dict) and "items" in data:
                data.setdefault("ok", True)
                data.setdefault("count", len(data.get("items") or []))
                return data
            if isinstance(data, list):
                return {"ok": True, "count": len(data), "items": data}
        except Exception:
            pass

    note = "Crypto news provider not configured"
    if not api_key:
        note = "Missing CRYPTO_PANIC_API_KEY – returning empty feed"
    return {"ok": True, "count": 0, "items": [], "note": note}










