# utils/approvals_gc.py
from __future__ import annotations
import os, asyncio, time, logging, json
from typing import Dict, Any, List, Optional

logger = logging.getLogger("algogpt.approvals.gc")

# Env
GC_ENABLE = (os.getenv("APPROVAL_GC_ENABLE","1").lower() in ("1","true","yes","on"))
GC_INTERVAL_SEC = int(os.getenv("APPROVAL_GC_INTERVAL_SEC","15"))
GC_BATCH_MAX = int(os.getenv("APPROVAL_GC_BATCH_MAX","50"))
NS = os.getenv("REDIS_NAMESPACE","ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL = os.getenv("REDIS_URL","").strip()

# Prometheus
try:
    from prometheus_client import Counter, Gauge
    approvals_expired_total = Counter("approvals_expired_total", "Total approvals auto-rejected by GC")
    approvals_gc_last_run_ts = Gauge("approvals_gc_last_run_ts", "Unix ts of last GC run")
    approvals_gc_last_expired = Gauge("approvals_gc_last_expired", "Number of approvals expired on last GC iteration")
except Exception:  # pragma: no cover
    approvals_expired_total = None  # type: ignore
    approvals_gc_last_run_ts = None  # type: ignore
    approvals_gc_last_expired = None  # type: ignore

# Optional Redis
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

async def _redis():
    if not (aioredis and REDIS_URL):
        return None
    return aioredis.from_url(REDIS_URL, decode_responses=True)

# ConfirmStore
try:
    from utils.approvals import ConfirmStore  # type: ignore
except Exception:
    class ConfirmStore:  # type: ignore
        @staticmethod
        def pending() -> List[Dict[str, Any]]: return []
        @staticmethod
        def reject(_idem: str, approver: Optional[str] = None) -> Dict[str, Any]: return {"ok":False}

# Telegram notifier (best-effort)
async def _notify_expired(idem: str, rec: Dict[str, Any]) -> None:
    try:
        from utils.telegram_notifier import notify_ops_alert  # type: ignore
        sym = (rec.get("symbol") or "").upper()
        side = (rec.get("side") or "?").upper()
        await notify_ops_alert(f"⏱️ כרטיס אישור פג תוקף: {idem} · {sym} {side}")
    except Exception:
        pass

# Digest logging (Redis list)
async def _log_expired_event(idem: str, rec: Dict[str, Any]) -> None:
    try:
        r = await _redis()
        if not r:
            return
        key = f"{NS}:expired_log"
        evt = {
            "ts": time.time(),
            "idem": idem,
            "symbol": (rec.get("symbol") or "").upper(),
            "side": (rec.get("side") or "").upper(),
            "ttl_sec": int(rec.get("ttl_sec") or 0),
        }
        await r.lpush(key, json.dumps(evt, ensure_ascii=False, separators=(",", ":")))
        await r.ltrim(key, 0, 2000)  # cap
    except Exception:
        pass

async def _gc_once() -> int:
    now = int(time.time())
    expired: List[Dict[str, Any]] = []
    for rec in ConfirmStore.pending() or []:
        try:
            cts = int(rec.get("created_ts") or rec.get("ts") or 0)
            ttl = int(rec.get("ttl_sec") or os.getenv("CONFIRM_TTL_SEC") or 0)
            if ttl > 0 and (now - cts) > ttl:
                expired.append(rec)
        except Exception:
            continue
        if len(expired) >= GC_BATCH_MAX:
            break

    # Reject and log
    cnt = 0
    for rec in expired:
        idem = str(rec.get("idem") or rec.get("ticket_id") or "")
        if not idem:
            continue
        try:
            ConfirmStore.reject(idem, approver="gc_expired")
            await _notify_expired(idem, rec)
            await _log_expired_event(idem, rec)
            cnt += 1
        except Exception as e:
            logger.warning({"event":"approval_gc.reject_failed","idem":idem,"err":str(e)})

    # Prometheus
    try:
        if approvals_expired_total and cnt:
            approvals_expired_total.inc(cnt)
        if approvals_gc_last_run_ts:
            approvals_gc_last_run_ts.set(time.time())
        if approvals_gc_last_expired is not None:
            approvals_gc_last_expired.set(cnt)
    except Exception:
        pass

    return cnt

async def approvals_gc_loop() -> None:
    if not GC_ENABLE:
        logger.info({"event":"approval_gc.disabled"})
        return
    logger.info({"event":"approval_gc.started","interval":GC_INTERVAL_SEC})
    try:
        while True:
            await asyncio.sleep(max(3, GC_INTERVAL_SEC))
            try:
                n = await _gc_once()
                if n:
                    logger.info({"event":"approval_gc.expired_rejected","count":n})
            except Exception as e:
                logger.warning({"event":"approval_gc.loop_error","err":str(e)})
    except asyncio.CancelledError:
        logger.info({"event":"approval_gc.cancelled"})

def start_gc_task(loop: Optional[asyncio.AbstractEventLoop] = None) -> asyncio.Task:
    lp = loop or asyncio.get_event_loop()
    return lp.create_task(approvals_gc_loop())



