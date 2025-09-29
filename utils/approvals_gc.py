# utils/approvals_gc.py
from __future__ import annotations
import os, asyncio, time, logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("algogpt.approvals.gc")

GC_ENABLE = (os.getenv("APPROVAL_GC_ENABLE","1").lower() in ("1","true","yes","on"))
GC_INTERVAL_SEC = int(os.getenv("APPROVAL_GC_INTERVAL_SEC","15"))
GC_BATCH_MAX = int(os.getenv("APPROVAL_GC_BATCH_MAX","50"))

try:
    from utils.approvals import ConfirmStore  # משתמש בConfirmStore המעודכן
except Exception:  # פולהבק
    class ConfirmStore:  # type: ignore
        @staticmethod
        def pending() -> List[Dict[str, Any]]: return []
        @staticmethod
        def reject(_idem: str, approver: Optional[str] = None) -> Dict[str, Any]: return {"ok":False}

# ה־notifier אופציונלי (best-effort)
async def _notify_expired(idem: str, rec: Dict[str, Any]) -> None:
    try:
        from utils.telegram_notifier import notify_ops_alert  # type: ignore
        sym = (rec.get("symbol") or "").upper()
        side = rec.get("side") or "?"
        await notify_ops_alert(f"⏱️ כרטיס אישור פג תוקף: {idem} · {sym} {side}")
    except Exception:
        pass

async def _gc_once() -> int:
    now = int(time.time())
    expired: List[Dict[str, Any]] = []
    for rec in ConfirmStore.pending():
        try:
            cts = int(rec.get("created_ts") or 0)
            ttl = int(rec.get("ttl_sec") or 0)
            if ttl > 0 and (now - cts) > ttl:
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
        except Exception as e:
            logger.warning({"event":"approval_gc.reject_failed","idem":idem,"err":str(e)})
    return len(expired)

async def approvals_gc_loop() -> None:
    if not GC_ENABLE:
        logger.info({"event":"approval_gc.disabled"})
        return
    logger.info({"event":"approval_gc.started","interval":GC_INTERVAL_SEC})
    while True:
        try:
            await asyncio.sleep(max(3, GC_INTERVAL_SEC))
            n = await _gc_once()
            if n:
                logger.info({"event":"approval_gc.expired_rejected","count":n})
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning({"event":"approval_gc.loop_error","err":str(e)})

# נקודת כניסה לstartup
def start_gc_task(loop: Optional[asyncio.AbstractEventLoop] = None) -> asyncio.Task:
    lp = loop or asyncio.get_event_loop()
    return lp.create_task(approvals_gc_loop())

