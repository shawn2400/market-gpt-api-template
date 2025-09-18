# routes/ops_guard.py
from __future__ import annotations
from fastapi import APIRouter, Query
from typing import Optional
import logging

router = APIRouter(tags=["ops"])

logger = logging.getLogger("algogpt.ops_guard.route")

try:
    from utils.ops_guard import ops_tick  # מחובר למנגנון Degrade/TTL וכו'
except Exception:
    async def ops_tick(**kw): return None

@router.get("/ops/guard/tick", include_in_schema=False)
async def ops_guard_tick(
    ws_reconnects: Optional[int] = Query(None),
    price_ttl_sec: Optional[float] = Query(None),
    exec_batch_timeout: bool = Query(False),
):
    await ops_tick(ws_reconnects=ws_reconnects, price_ttl_sec=price_ttl_sec, exec_batch_timeout=exec_batch_timeout)
    return {"ok": True, "ws_reconnects": ws_reconnects, "price_ttl_sec": price_ttl_sec, "exec_batch_timeout": exec_batch_timeout}

