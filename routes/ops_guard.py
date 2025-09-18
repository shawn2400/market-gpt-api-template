# routes/ops_guard.py
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter(tags=["ops"])

logger = logging.getLogger("algogpt.ops_guard.route")

# חיבור למנגנון Degrade/TTL/Alerts. אם אין – הניתוב לא יקרוס.
try:
    from utils.ops_guard import ops_tick  # type: ignore
except Exception:
    async def ops_tick(**kw):  # type: ignore
        return None

@router.get("/ops/guard/tick", include_in_schema=False)
async def ops_guard_tick(
    ws_reconnects: Optional[int] = Query(None, description="מספר Reconnects של ה־WS בתקופה האחרונה"),
    price_ttl_sec: Optional[float] = Query(None, description="גיל עדכון מחיר אחרון (שניות)"),
    exec_batch_timeout: bool = Query(False, description="האם היה Timeout בבאץ' ביצוע לאחרונה"),
):
    """
    נקודת איסוף רכה למצב אופס — מעדכנת את מנגנון השמירה (TTL / עומסים / Degrade Mode).
    (מוגן ע״י האימות הגלובלי של ה־API; לא נוסף ל־public paths.)
    """
    await ops_tick(
        ws_reconnects=ws_reconnects,
        price_ttl_sec=price_ttl_sec,
        exec_batch_timeout=exec_batch_timeout,
    )
    return {
        "ok": True,
        "ws_reconnects": ws_reconnects,
        "price_ttl_sec": price_ttl_sec,
        "exec_batch_timeout": exec_batch_timeout,
    }
