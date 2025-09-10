# utils/ops_guard.py
from __future__ import annotations
import os, time
from typing import Optional
from utils.metrics import metrics_tracker as mx
from utils.telegram_notifier import notify_error, notify_info

_last_ttl_alert_ts: float = 0.0
_last_to_timeout_alert_ts: float = 0.0
_last_backpressure_notice_ts: float = 0.0
_last_drift_alert_ts: float = 0.0

def _suppress(last_ts: float, cool_sec: int) -> bool:
    return (time.time() - last_ts) < cool_sec

async def ops_tick(*, current_interval: int, last_tick_sec: float) -> None:
    """
    נקרא פעם לטיק של ה-Executor:
      1) Alerting: WS TTL, burst של timeouts.
      2) Backpressure: אם זמן טיק בפועל גבוה מה-Hi watermark -> הודעה (האוטוטיון שלך יעלה מרווח).
      3) Anchors Sticking: מעבר זמני ל-Mark-only + FEAT_MARK_INDEX_SANITY=1 כש-WS בעייתי.
      4) Price Drift Monitor (אם קיימים API מתאימים).
    """
    global _last_ttl_alert_ts, _last_to_timeout_alert_ts, _last_backpressure_notice_ts, _last_drift_alert_ts

    cool = int(os.getenv("ALERT_COOLDOWN_SEC", "120"))

    # (1) TTL Alerts
    ttl = float(mx.get_metrics()["gauges"].get("ws.price_ttl_sec", 0.0))
    ttl_lim = float(os.getenv("PRICE_TTL_ALERT_SEC", "10"))
    if ttl > ttl_lim and not _suppress(_last_ttl_alert_ts, cool):
        _last_ttl_alert_ts = time.time()
        await notify_error(f"⚠️ מחירי WS לא רעננים: TTL≈{ttl:.1f}s (> {ttl_lim}s) — בדוק רשת/פיד")

    # (1b) Timeout bursts
    to_count = int(mx.get_metrics()["counters"].get("exec.batch_timeouts", 0))
    burst = int(os.getenv("EXEC_TIMEOUT_ALERT_BURST", "3"))
    if to_count >= burst and not _suppress(_last_to_timeout_alert_ts, cool):
        _last_to_timeout_alert_ts = time.time()
        await notify_error(f"⚠️ עומס סורק: {to_count} timeouts — שקול להעלות interval/להוריד concurrency")

    # (2) Backpressure notice
    ew = last_tick_sec * 1000.0
    hi = float(os.getenv("BACKPRESSURE_HI_WATERMARK_MS", "7500"))
    if ew > hi and not _suppress(_last_backpressure_notice_ts, cool):
        _last_backpressure_notice_ts = time.time()
        await notify_info(f"ℹ️ Scan tick ~{ew:.0f}ms > {hi:.0f}ms — Auto-Tune יגדיל מרווח (ניטור)")

    # (3) Anchors Sticking → Degrade Mode
    try:
        from utils.ws_user_stats import maybe_activate_degrade, mark_only_mode_active
        activated = maybe_activate_degrade()
        if activated or mark_only_mode_active():
            os.environ["FEAT_MARK_INDEX_SANITY"] = os.getenv("FEAT_MARK_INDEX_SANITY", "0") or "1"
            os.environ["WS_PRICE_MODE"] = "mark"
    except Exception:
        pass

    # (4) Price Drift Monitor (אופציונלי; ירוץ רק אם קיים API ל-index)
    try:
        DRIFT_BPS_ALERT = float(os.getenv("PRICE_DRIFT_ALERT_BPS", "25.0"))
        from utils.binance_client import futures_mark_price as _mark
        try:
            from utils.binance_client import futures_index_price as _index  # אם קיים אצלך
        except Exception:
            _index = None  # אין — מדלגים
        if _index:
            # בוחרים סימבול מייצג (אפשר לשנות ל-HEALTH_SYMBOLS/Watchlist ראשון)
            sym = os.getenv("DRIFT_MONITOR_SYMBOL", "BTCUSDT").upper()
            mp = float(_mark(sym) or 0.0)
            ip = float(_index(sym) or 0.0)
            if mp > 0 and ip > 0:
                drift_bps = abs(mp - ip) / ip * 10_000.0
                mx.set_gauge("price.drift_bps", drift_bps)
                if drift_bps >= DRIFT_BPS_ALERT and not _suppress(_last_drift_alert_ts, cool):
                    _last_drift_alert_ts = time.time()
                    await notify_error(f"⚠️ Price drift גבוה ב-{sym}: ~{drift_bps:.1f}bps — sanity מחמיר, שקול השהיה")
                    os.environ["FEAT_MARK_INDEX_SANITY"] = "1"
    except Exception:
        pass

