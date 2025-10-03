# utils/approvals_digest_job.py
from __future__ import annotations
"""
Expired-Approvals Digest Job

- מריץ באופן תקופתי שליחת דוח דייג'סט לאישורים שפג תוקפם.
- יציב, אדמפוטנטי, ונסגר נקי ב־shutdown (אין "Task was destroyed but it is pending!").
- תצורה דרך משתני סביבה (עם ברירות מחדל סבירות):
    * OPS_DIGEST_ENABLE=1|0                 (ברירת מחדל: 1)
    * OPS_DIGEST_INTERVAL_HOURS=float       (ברירת מחדל: 3)
    * OPS_DIGEST_BACKOFF_ON_ERROR_SEC=float (ברירת מחדל: 15)
    * OPS_DIGEST_RUN_IMMEDIATE=1|0          (ברירת מחדל: 0) — להריץ מיד בהפעלה
    * OPS_DIGEST_LOOKBACK_HOURS=float       (ברירת מחדל: =OPS_DIGEST_INTERVAL_HOURS)
"""

import os
import asyncio
import logging
from typing import Optional

log = logging.getLogger("algogpt.approvals.digest_job")

# --- תלות רכה בטלגרם / נוטיפיקציה ---
try:
    # צפוי להימצא ב-proj: utils/telegram_notifier_core.py
    from utils.telegram_notifier_core import send_ops_digest_now as _send_ops_digest_now  # type: ignore
except Exception:
    async def _send_ops_digest_now(hours: Optional[int] = None) -> None:  # noqa: N802
        # פולבאק: אם אין תלות — לא נכשלים, רק לוג.
        log.info(
            {
                "event": "digest.send.noop",
                "reason": "telegram_notifier_core_missing",
                "hours": hours,
            }
        )
        await asyncio.sleep(0)  # שמירה על ממשק אסינכרוני

# --- תצורה מהסביבה ---
def _as_bool(v: Optional[str], default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")

def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

OPS_DIGEST_ENABLE: bool = _as_bool(os.getenv("OPS_DIGEST_ENABLE", "1"), True)
OPS_DIGEST_INTERVAL_HOURS: float = _float_env("OPS_DIGEST_INTERVAL_HOURS", 3.0)
OPS_DIGEST_BACKOFF_ON_ERROR_SEC: float = _float_env("OPS_DIGEST_BACKOFF_ON_ERROR_SEC", 15.0)
OPS_DIGEST_RUN_IMMEDIATE: bool = _as_bool(os.getenv("OPS_DIGEST_RUN_IMMEDIATE", "0"), False)
OPS_DIGEST_LOOKBACK_HOURS: float = _float_env(
    "OPS_DIGEST_LOOKBACK_HOURS", OPS_DIGEST_INTERVAL_HOURS
)

# מינימוםים סבירים כדי לא להעמיס:
_MIN_INTERVAL_SEC = 60.0
_MIN_BACKOFF_SEC = 5.0

# --- מצב גלובלי של המשימה ---
_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None


async def _sleep_or_stop(timeout_sec: float) -> bool:
    """
    ישן עד timeout_sec או עד שמתקבל stop.
    מחזיר True אם הופסק (stop), אחרת False.
    """
    global _stop_event
    if _stop_event is None:
        _stop_event = asyncio.Event()
    try:
        await asyncio.wait_for(_stop_event.wait(), timeout=timeout_sec)
        return True  # הופסק
    except asyncio.TimeoutError:
        return False  # נגמר הטיימאאוט, ממשיכים


async def _do_digest_once() -> None:
    """
    מריץ מחזור דוח אחד.
    """
    hours = OPS_DIGEST_LOOKBACK_HOURS
    try:
        await _send_ops_digest_now(int(hours) if hours is not None else None)
        log.info({"event": "digest.sent_ok", "lookback_hours": hours})
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning({"event": "digest.sent_fail", "error": str(e)})


async def _digest_loop() -> None:
    """
    לולאת דייג'סט מרכזית — בטוחה לביטול, עם backoff על שגיאות.
    """
    interval_sec = max(OPS_DIGEST_INTERVAL_HOURS * 3600.0, _MIN_INTERVAL_SEC)
    backoff_sec = max(OPS_DIGEST_BACKOFF_ON_ERROR_SEC, _MIN_BACKOFF_SEC)

    log.info(
        {
            "event": "digest.loop.start",
            "enabled": OPS_DIGEST_ENABLE,
            "interval_sec": interval_sec,
            "lookback_hours": OPS_DIGEST_LOOKBACK_HOURS,
            "run_immediate": OPS_DIGEST_RUN_IMMEDIATE,
        }
    )

    # ריצה מיידית אם התבקש
    if OPS_DIGEST_RUN_IMMEDIATE:
        try:
            await _do_digest_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning({"event": "digest.first_run_fail", "error": str(e)})
            # backoff קצר ואז נמשיך למחזוריות
            stopped = await _sleep_or_stop(backoff_sec)
            if stopped:
                return

    # מחזוריות
    while True:
        try:
            stopped = await _sleep_or_stop(interval_sec)
            if stopped:
                log.info({"event": "digest.loop.stop_signal"})
                return

            await _do_digest_once()

        except asyncio.CancelledError:
            log.info({"event": "digest.loop.cancelled"})
            raise
        except Exception as e:
            # לא מפילים את הלופ; יש backoff וניסיון נוסף
            log.warning({"event": "digest.loop.error", "error": str(e)})
            stopped = await _sleep_or_stop(backoff_sec)
            if stopped:
                return


def start_expired_digest_job() -> Optional[asyncio.Task]:
    """
    מפעיל את משימת הדייג'סט אם OPS_DIGEST_ENABLE=1.
    אדמפוטנטי: אם המשימה כבר רצה — מחזיר את הקיימת.
    """
    global _task, _stop_event

    if not OPS_DIGEST_ENABLE:
        log.info({"event": "digest.skip_disabled"})
        return None

    if _task and not _task.done():
        log.info({"event": "digest.already_running"})
        return _task

    # איפוס stop-event והקמת משימה חדשה
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_digest_loop(), name="expired_digest_job")
    log.info({"event": "digest.started"})
    return _task


async def stop_expired_digest_job() -> bool:
    """
    עוצר את משימת הדייג'סט (אם רצה) בצורה נקייה.
    מחזיר True אם הייתה משימה לעצור, אחרת False.
    """
    global _task, _stop_event
    if not _task:
        return False

    if _stop_event:
        _stop_event.set()

    try:
        _task.cancel()
    except Exception:
        pass

    try:
        await _task
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.warning({"event": "digest.stop.error", "error": str(e)})

    _task = None
    return True


def is_running() -> bool:
    """האם משימת הדייג'סט פעילה?"""
    return bool(_task and not _task.done())


def get_task() -> Optional[asyncio.Task]:
    """קבלת ה-Task (אם קיים)."""
    return _task


__all__ = [
    "start_expired_digest_job",
    "stop_expired_digest_job",
    "is_running",
    "get_task",
]

