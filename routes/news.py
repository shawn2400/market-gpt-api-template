# routes/news.py
from __future__ import annotations
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, Query
import asyncio, os

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

from utils.cache import aget_or_set
from utils.news_utils import fetch_crypto_news, analyze_news_impact

TTL_NEWS = float(os.getenv("CACHE_TTL_NEWS", "120"))  # 2 דקות

router = APIRouter(prefix="/news", tags=["News"], dependencies=[Depends(require_bearer_token)])

@router.get(
    "/crypto",
    summary="Crypto news (CryptoPanic) with impact score",
    operation_id="getCryptoNews",
)
async def get_crypto_news(filter: Optional[str] = Query(None)) -> Dict[str, Any]:
    """
    מחזיר 200 תמיד.
    אם חסר API Key – מחזיר רשימה ריקה + note.
    """
    key = f"news|{filter or ''}"

    async def _load():
        items = await asyncio.to_thread(
            fetch_crypto_news,
            True,              # silent_on_missing_key: לא להיכשל אם אין מפתח
            filter or "",      # פילטר אופציונלי: hot/rising/important/bullish/bearish
            50,                # limit
        )
        scored = await asyncio.to_thread(analyze_news_impact, items)
        return {"ok": True, "count": len(scored), "items": scored}

    # Cache לזמן קצר כדי להימנע מספאם ל־CryptoPanic
    return await aget_or_set(key, TTL_NEWS, _load)



