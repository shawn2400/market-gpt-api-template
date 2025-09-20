# routes/news.py
from __future__ import annotations
import time
from typing import Dict, List
from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel

from utils.auth import require_api_key
from utils.storage import save_payload, cleanup_static

router = APIRouter(tags=["News"], dependencies=[Depends(require_api_key)])

# מצערת פשוטה כדי למנוע עומס בשירות חיצוני/קבצים:
_COOLDOWN_SEC = 5   # אפשר לכוון ב-ENV אם תרצה
_last_call_ts: float = 0.0

class NewsResponse(BaseModel):
    ok: bool = True
    url: str

def _throttle_or_raise():
    global _last_call_ts
    now = time.time()
    if (now - _last_call_ts) < _COOLDOWN_SEC:
        # לא חוסם – רק מאט ומחזיר 429 עדין
        raise HTTPException(status_code=429, detail=f"news cooldown, try again in {int(_COOLDOWN_SEC - (now - _last_call_ts))}s")
    _last_call_ts = now

@router.get("/latest", response_model=NewsResponse)
async def latest_news(limit: int = Query(20, ge=1, le=100)) -> NewsResponse:
    """
    מביא חדשות → שומר בקובץ static → מחזיר URL.
    * קליל כברירת מחדל — אין שליפות חיצוניות כאן.
    * מצערת פנימית למניעת הצפה.
    """
    _throttle_or_raise()

    # קאפ קשיח מעבר ל-Query כדי למנוע עומס גם אם שינו סכמות:
    limit = max(1, min(int(limit), 50))

    # fake data (כאן תוכל לחבר ל-provider אמיתי בעתיד)
    items: List[Dict] = [{"title": f"News {i}", "source": "CryptoPanic"} for i in range(limit)]

    # שמירה לקובץ סטטי עם TTL קצר (ב-storage יש גם mirroring אופציונלי ל-Redis)
    url = save_payload({"items": items}, expire=600)

    # ניקוי עדין של קבצים ישנים (לא כבד)
    cleanup_static(max_files=300)

    return NewsResponse(ok=True, url=url)












