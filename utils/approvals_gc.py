# utils/approvals_gc.py
from __future__ import annotations
import os, asyncio, time, logging, json
from typing import Dict, Any, List, Optional

logger = logging.getLogger("algogpt.approvals.gc")

GC_ENABLE = (os.getenv("APPROVAL_GC_ENABLE","1").lower() in ("1","true","yes","on"))
GC_INTERVAL_SEC_DEFAULT = int(os.getenv("APPROVAL_GC_INTERVAL_SEC","15"))
GC_BATCH_MAX = int(os.getenv("APPROVAL_GC_BATCH_MAX","50"))

# Optional Redis for digest log
NS        = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL = os.getenv("REDIS_URL", "").strip()
EXPIRED_LOG_KEY = f"{NS}:approvals_expired_log"
EXPIRED_LOG_TTL_SEC = 48 * 3600  # נשמר יומיים
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

async def _redis():
    if not (aioredis and REDIS_URL):
        return None
    return aioredis.from_url(REDIS_URL, decode_responses=True)

# Prometheus
try:
    from prometheus_client import Counter, Gauge
    C_EXPIRED = Counter("approvals_expired_total", "Total approvals auto-rejected due to TTL", ["reason"])
    G_LASTRUN = Gauge("approvals_gc_last_run_ts", "Unix timestamp of last approvals GC run")
except Exception:
    C_EXPIRED = None  # type: ignore
    G_LASTRUN = None  # type: ignore

try:
    from utils.approvals import ConfirmStore  # משתמש בConfirmStore המעודכן
except Exception:  # פולהבק
    class ConfirmStore:  # type: ignore
        @staticmethod
        def pending() -> List[Dict[str, Any]]: return []
        @staticmethod
        def reject(_idem: str, approver: Optional[str] = None) -> Dict[str, Any]: return {"ok":False}

# notifier אופציונלי (best-effort)
async def _notify_expired(idem: str, rec: Dict[str, Any]) -> None:
    try:
        from utils.telegram_notifier import notify_ops_alert  # type: ignore
        sym = (rec.get("symbol") or "").upper()
        side = (rec.get("side") or "?").upper()
        await notify_ops_alert(f"⏱️ כרטיס אישור פג תוקף: {idem} · {sym} {side}")
    except Exception:
        pass

async def _log_expired(rec: Dict[str, Any]) -> None:
    """שומר רשומה 'קלה' ל-Redis לצורך דוח digest."""
    try:
        r = await _redis()
        if not r: return
        row = {
            "ts": int(time.time()),
            "idem": rec.get("idem") or rec.get("ticket_id"),
            "symbol": (rec.get("symbol") or "").upper(),
            "side": (rec.get("side") or "").upper(),
            "score": rec.get("score"),
            "ttl_sec": rec.get("ttl_sec"),
            "created_ts": rec.get("created_ts") or rec.get("ts"),
        }
        await r.lpush(EXPIRED_LOG_KEY, json.dumps(row, ensure_ascii=False, separators=(",",":")))
        await r.expire(EXPIRED_LOG_KEY, EXPIRED_LOG_TTL_SEC)
        # שמירה שהליסט לא יתנפח
        await r.ltrim(EXPIRED_LOG_KEY, 0, 1999)
    except Exception:
        pass

async def _gc_once(now_ts: Optional[int] = None) -> int:
    now = int(now_ts or time.time())
    expired: List[Dict[str, Any]] = []
    for rec in (ConfirmStore.pending() or []):
        try:
            cts = int(rec.get("created_ts") or rec.get("ts") or 0)
            ttl = int(rec.get("ttl_sec") or int(os.getenv("CONFIRM_TTL_SEC","0")) or 0)
            if ttl > 0 and cts > 0 and (now - cts) > ttl:
                expired.append(rec)
        except Exception:
            continue
        if len(expired) >= GC_BATCH_MAX:
            break

    for rec in expired:
        idem = str(rec.get("idem") or rec.get("ticket_id") or "")
        if not idem:
            continue
        try:
            ConfirmStore.reject(idem, approver="gc_expired")
            await _notify_expired(idem, rec)
            await _log_expired({"idem": idem, **rec})
        except Exception as e:
            logger.warning({"event":"approval_gc.reject_failed","idem":idem,"err":str(e)})

    # metrics
    try:
        if G_LASTRUN: G_LASTRUN.set(now)
        if C_EXPIRED and expired: C_EXPIRED.labels(reason="ttl").inc(len(expired))
    except Exception:
        pass

    return len(expired)

async def approvals_gc_loop(interval_sec: Optional[int] = None) -> None:
    if not GC_ENABLE:
        logger.info({"event":"approval_gc.disabled"})
        return
    interval = int(interval_sec or GC_INTERVAL_SEC_DEFAULT)
    logger.info({"event":"approval_gc.started","interval":interval})
    try:
        while True:
            await asyncio.sleep(max(3, interval))
            try:
                n = await _gc_once()
                if n:
                    logger.info({"event":"approval_gc.expired_rejected","count":n})
            except Exception as e:
                logger.warning({"event":"approval_gc.loop_error","err":str(e)})
    except asyncio.CancelledError:
        logger.info({"event":"approval_gc.cancelled"})

# Starters תואמים לשתי הגרסאות שראיתי אצלך:
def start_gc_task(loop: Optional[asyncio.AbstractEventLoop] = None, interval: Optional[int] = None) -> asyncio.Task:
    lp = loop or asyncio.get_event_loop()
    return lp.create_task(approvals_gc_loop(interval_sec=interval))

def start_approvals_gc(interval: Optional[int] = None, loop: Optional[asyncio.AbstractEventLoop] = None) -> asyncio.Task:
    lp = loop or asyncio.get_event_loop()
    return lp.create_task(approvals_gc_loop(interval_sec=interval))


