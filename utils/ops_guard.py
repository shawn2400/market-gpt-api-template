# utils/ops_guard.py
from __future__ import annotations
import os, time
from typing import Optional
from utils.metrics import metrics_tracker as mx
from utils.telegram_notifier import notify_error, notify_info

_last_ttl_alert_ts: float = 0.0
_last_to_timeout_alert_ts: float = 0.0
_last_backpressure_notice_ts: float = 0.0

def _should_suppress(last_ts: float, cool_sec: int) -> bool:
    return (time.time() - last_ts) < cool_sec

async def ops_tick(*, current_interval: int, last_tick_sec: float) -> None:
    """
    נקרא פעם בטיק של ה-Executor.
    1) Alerting פשוט על price TTL ועל batch timeouts.
    2) Backpressure: אם הממוצע בפועל חורג – מרימים הודעת כוונון (האוטוטיון שלך כבר עושה את העדכון בפועל).
    3) 'Sticking Anchors': אם ws בעייתי → מפעיל מצב mark-only + מחמיר sanity.
    """
    global _last_ttl_alert_ts, _last_to_timeout_alert_ts, _last_backpressure_notice_ts

    # 1) TTL מחירים
    ttl = float(mx.get_metrics()["gauges"].get("ws.price_ttl_sec", 0.0))
    ttl_lim = float(os.getenv("PRICE_TTL_ALERT_SEC", "10"))
    cool = int(os.getenv("ALERT_COOLDOWN_SEC", "120"))
    if ttl > ttl_lim and not _should_suppress(_last_ttl_alert_ts, cool):
        _last_ttl_alert_ts = time.time()
        await notify_error(f"⚠️ WS price TTL high: {ttl:.1f}s (>{ttl_lim}s) — בודק רעננות/רשת")

    # 2) Timeouts Burst
    to_count = int(mx.get_metrics()["counters"].get("exec.batch_timeouts", 0))
    burst = int(os.getenv("EXEC_TIMEOUT_ALERT_BURST", "3"))
    if to_count >= burst and not _should_suppress(_last_to_timeout_alert_ts, cool):
        _last_to_timeout_alert_ts = time.time()
        await notify_error(f"⚠️ Scanner timeouts burst: {to_count} (>{burst-1}) — שקול SCAN_CONCURRENCY/interval")

    # 3) Backpressure (הודעת המלצה בלבד — האוטוטיון שלך יבצע בפועל)
    ew = last_tick_sec * 1000.0
    hi = float(os.getenv("BACKPRESSURE_HI_WATERMARK_MS", "7000"))  # ~SCAN_TIME_BUDGET_SEC*1000
    if ew > hi and not _should_suppress(_last_backpressure_notice_ts, cool):
        _last_backpressure_notice_ts = time.time()
        await notify_info(f"ℹ️ Scan tick EWMA~{ew:.0f}ms > {hi:.0f}ms — Auto-Tune יעלה את המרווח (ניטור)")

    # 4) Sticking Anchors — העברה ל-mark-price + הקשחת sanity אם reconnects גבוה
    try:
        from utils.ws_user_stats import maybe_activate_degrade, mark_only_mode_active
        activated = maybe_activate_degrade()
        if activated or mark_only_mode_active():
            os.environ["FEAT_MARK_INDEX_SANITY"] = os.getenv("FEAT_MARK_INDEX_SANITY","0") or "1"
            os.environ["WS_PRICE_MODE"] = "mark"
    except Exception:
        pass
