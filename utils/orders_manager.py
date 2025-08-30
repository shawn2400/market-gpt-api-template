# utils/orders_manager.py
from __future__ import annotations

import os
import json
import time
import logging
from typing import Any, Dict, List, Optional
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger("algogpt.orders")

# קונפיג
REDIS_URL = os.getenv("REDIS_URL", "")
MAX_LOG_LEN = int(os.getenv("ORDERS_MAX_LOG_LEN", "200"))
RECORD_DRYRUN = (os.getenv("ORDERS_RECORD_DRYRUN", "0").strip().lower() in ("1", "true", "yes", "on"))

# Backend: Redis אם קיים, אחרת In-Memory
_redis = None
if REDIS_URL:
    try:
        import redis  # type: ignore
        _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        # בדיקה רכה
        _redis.ping()
        logger.info(f"[Orders] using Redis backend: {REDIS_URL}")
    except Exception as e:
        logger.warning(f"[Orders] Redis unavailable ({e}), falling back to memory")
        _redis = None
else:
    logger.info("[Orders] Redis URL not set, using memory backend")

_mem_log: deque[str] = deque(maxlen=MAX_LOG_LEN)

LOG_KEY = "orders:log"  # Redis list

OPEN_STATUSES = {"NEW", "PARTIALLY_FILLED", "PENDING_NEW", "ACCEPTED", "DRY_RUN"}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _push_record(rec: Dict[str, Any]) -> None:
    data = json.dumps(rec, ensure_ascii=False)
    if _redis:
        try:
            _redis.lpush(LOG_KEY, data)
            _redis.ltrim(LOG_KEY, 0, MAX_LOG_LEN - 1)
            return
        except Exception as e:
            logger.warning(f"[Orders] redis push failed: {e}")
    _mem_log.appendleft(data)

def _iter_log() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if _redis:
        try:
            items = _redis.lrange(LOG_KEY, 0, MAX_LOG_LEN - 1)
            for s in items:
                try:
                    out.append(json.loads(s))
                except Exception:
                    pass
            return out
        except Exception as e:
            logger.warning(f"[Orders] redis read failed: {e}")
    # memory
    for s in list(_mem_log):
        try:
            out.append(json.loads(s))
        except Exception:
            pass
    return out

def record_order(
    *,
    order_id: Optional[int] = None,
    client_id: Optional[str] = None,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    status: str,
    extra: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """רישום הזמנה ליומן (Redis/Memory)."""
    if dry_run and not RECORD_DRYRUN:
        # ברירת מחדל: לא לרשום DRY_RUN כדי לא "ללכלך" היסטוריה
        return {}
    oid = str(order_id) if order_id is not None else (client_id or f"dry-{int(time.time()*1000)}")
    rec: Dict[str, Any] = {
        "id": oid,
        "symbol": symbol.upper(),
        "side": side.upper(),
        "qty": float(qty),
        "price": float(price),
        "status": str(status or ("DRY_RUN" if dry_run else "NEW")).upper(),
        "created_at": _now_iso(),
    }
    if client_id:
        rec["client_id"] = client_id
    if extra:
        rec["extra"] = extra
    _push_record(rec)
    return rec

def update_order_status(order_id_or_client: str, new_status: str) -> bool:
    """עדכון סטטוס להזמנה קיימת בלוג."""
    items = _iter_log()
    updated = False
    for rec in items:
        if rec.get("id") == order_id_or_client or rec.get("client_id") == order_id_or_client:
            rec["status"] = new_status.upper()
            rec["updated_at"] = _now_iso()
            _push_record(rec)  # push as new head (שומר היסטוריה)
            updated = True
            break
    return updated

def get_orders(*, symbol: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), MAX_LOG_LEN))
    items = _iter_log()
    if symbol:
        sym = symbol.upper()
        items = [x for x in items if (x.get("symbol") or "").upper() == sym]
    return items[:limit]

def get_active_orders() -> List[Dict[str, Any]]:
    items = _iter_log()
    return [x for x in items if str(x.get("status", "")).upper() in OPEN_STATUSES]

