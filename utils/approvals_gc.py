# utils/approvals_gc.py
from __future__ import annotations
import os, asyncio, time, logging, json
from typing import Dict, Any, List, Optional

logger = logging.getLogger("algogpt.approvals.gc")

GC_ENABLE = (os.getenv("APPROVAL_GC_ENABLE","1").lower() in ("1","true","yes","on"))
GC_INTERVAL_SEC = int(os.getenv("APPROVAL_GC_INTERVAL_SEC","15"))
GC_BATCH_MAX = int(os.getenv("APPROVAL_GC_BATCH_MAX","50"))
NS = os.getenv("REDIS_NAMESPACE","ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL = os.getenv("REDIS_URL","").strip()

# ---- metrics tracker (internal JSON)
try:
    from utils.metrics import metrics_tracker
except Exception:
    metrics_tracker = None  # type: ignore

# ---- Prometheus
try:
    from prometheus_client import Counter, Gauge
    approvals_expired_total = Counter("approvals_expired_total", "Total approvals auto-rejected by GC")
    approvals_gc_last_run_ts = Gauge("approvals_gc_last_run_ts", "Unix ts of last GC run")
    approvals_gc_last_expired = Gauge("approvals_gc_last_expired", "Number of approvals expired on last GC iteration")
    # labels (opt-in, low-cardinality!)
    LABELS_ENABLE = os.getenv("APPROVALS_LABELS_ENABLE","0").lower() in ("1","true","yes","on")
    APPROVALS_LABELS_SYMBOLS = {s.strip().upper() for s in (os.getenv("APPROVALS_LABELS_SYMBOLS","") or "").split(",") if s.strip()}
    if not APPROVALS_LABELS_SYMBOLS:
        APPROVALS_LABELS_SYMBOLS = {s.strip().upper() for s in (os.getenv("WATCHLIST","") or "").split(",") if s.strip()}
    approvals_expired_by_symbol = Counter("approvals_expired_by_symbol",
                                          "Expired approvals by (symbol,side) – gated",
                                          ["symbol","side"]) if LABELS_ENABLE else None
except Exception:
    approvals_expired_total = approvals_gc_last_run_ts = approvals_gc_last_expired = None  # type: ignore
    approvals_expired_by_symbol = None  # type: ignore
    LABELS_ENABLE = False

# ---- Optional Redis
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

async def _redis():
    if not (aioredis and REDIS_URL):
        return None
    return aioredis.from_url(REDIS_URL, decode_responses=True)

# ---- ConfirmStore
try:
    from utils.approvals import ConfirmStore  # type: ignore
except Exception:
    class ConfirmStore:  # type: ignore
        @staticmethod
        def pending() -> List[Dict[str, Any]]: return []
        @staticmethod
        def reject(_idem: str, approver: Optional[str] = None) -> Dict[str, Any]: return {"ok":False}

# ---- notifier (best-effort)
async def _notify_expired(idem: str, rec: Dict[str, Any]) -> None:
    try:
        from utils.telegram_notifier import notify_ops_alert  # type: ignore
        sym = (rec.get("symbol") or "").upper()
        side = (rec.get("side") or "?").upper()
        await notify_ops_alert(f"⏱️ כרטיס אישור פג תוקף: {idem} · {sym} {side}")
    except Exception:
        pass

# ---- log for digest (Redis list)
async def _log_expired_event(idem: str, rec: Dict[str, Any]) -> None:
    try:
        r = await _redis()
        if not r: return
        key = f"{NS}:expired_log"
        evt = {"ts": time.time(),
               "idem": idem,
               "symbol": (rec.get("symbol") or "").upper(),
               "side": (rec.get("side") or "").upper(),
               "ttl_sec": int(rec.get("ttl_sec") or 0)}
        await r.lpush(key, json.dumps(evt, ensure_ascii=False, separators=(",", ":")))
        await r.ltrim(key, 0, 2000)
    except Exception:
        pass

async def _gc_once() -> int:
    now = int(time.time())
    expired: List[Dict[str, Any]] = []
    for rec in (ConfirmStore.pending() or []):
        try:
            cts = int(rec.get("created_ts") or rec.get("ts") or 0)
            ttl = int(rec.get("ttl_sec") or os.getenv("CONFIRM_TTL_SEC") or 0)
            if ttl > 0 and (now - cts) > ttl:
                expired.append(rec)
        except Exception:
            continue
        if len(expired) >= GC_BATCH_MAX:
            break

    cnt = 0
    for rec in expired:
        idem = str(rec.get("idem") or rec.get("ticket_id") or "")
        if not idem: continue
        try:
            ConfirmStore.reject(idem, approver="gc_expired")
            await _notify_expired(idem, rec)
            await _log_expired_event(idem, rec)
            cnt += 1

            # ---- metrics (internal JSON)
            if metrics_tracker:
                metrics_tracker.inc_counter("approvals_expired_total", 1.0)
                sym = (rec.get("symbol") or "").upper()
                side = (rec.get("side") or "").upper()
                # נעשה גם מונה עם labels פנימיים (לא Prometheus)
                metrics_tracker.inc_counter("approvals_expired_labelled", 1.0, labels={"symbol": sym, "side": side})

            # ---- Prometheus labelled (gated & safe)
            if approvals_expired_by_symbol:
                sym = (rec.get("symbol") or "").upper()
                side = (rec.get("side") or "").upper()
                if (not APPROVALS_LABELS_SYMBOLS) or (sym in APPROVALS_LABELS_SYMBOLS):
                    approvals_expired_by_symbol.labels(symbol=sym, side=side).inc()

        except Exception as e:
            logger.warning({"event":"approval_gc.reject_failed","idem":idem,"err":str(e)})

    try:
        # Prometheus gauges/counter
        if approvals_expired_total and cnt:
            approvals_expired_total.inc(cnt)
        if approvals_gc_last_run_ts:
            approvals_gc_last_run_ts.set(time.time())
        if approvals_gc_last_expired is not None:
            approvals_gc_last_expired.set(cnt)

        # Internal gauges
        if metrics_tracker:
            metrics_tracker.set_gauge("approvals_gc_last_run_ts", time.time())
            metrics_tracker.set_gauge("approvals_gc_last_expired", float(cnt))
    except Exception:
        pass

    return cnt

async def approvals_gc_loop(interval: Optional[int] = None) -> None:
    if not GC_ENABLE:
        logger.info({"event":"approval_gc.disabled"}); return
    iv = max(3, int(interval or GC_INTERVAL_SEC))
    logger.info({"event":"approval_gc.started","interval":iv})
    try:
        while True:
            await asyncio.sleep(iv)
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

def start_approvals_gc(interval: Optional[int] = None):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    loop.create_task(approvals_gc_loop(interval=interval))
    return True






