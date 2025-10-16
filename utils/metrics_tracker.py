# -*- coding: utf-8 -*-
from __future__ import annotations
import time
import os
from typing import Dict, Any, Optional, List

_START_TIME = time.time()
_SENT_TELEGRAM = 0
_FAILED_TELEGRAM = 0

# psutil אופציונלי
try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except Exception:
    _HAS_PSUTIL = False

# ---- basic counters ----
_APPROVE_OK = 0
_APPROVE_FAIL = 0
_REJECT = 0
_SCAN_EVALS = 0
_SCAN_PASSED = 0
_SCAN_BLOCKED = 0

# last computed checklist score (gauge)
_LAST_ENTRY_SCORE: Optional[float] = None

def set_last_entry_score(val: Optional[float]) -> None:
    """שומר מדד ציון כניסה אחרון (0..10)."""
    global _LAST_ENTRY_SCORE
    try:
        _LAST_ENTRY_SCORE = None if val is None else float(val)
    except Exception:
        _LAST_ENTRY_SCORE = None

def get_last_entry_score() -> Optional[float]:
    """מאפשר קריאה של הציון האחרון (ל־/meta או דשבורד)."""
    return _LAST_ENTRY_SCORE

def record_telegram_sent() -> None:
    global _SENT_TELEGRAM
    _SENT_TELEGRAM += 1

def record_telegram_failed() -> None:
    global _FAILED_TELEGRAM
    _FAILED_TELEGRAM += 1

def inc_approve_ok() -> None:
    global _APPROVE_OK
    _APPROVE_OK += 1

def inc_approve_fail() -> None:
    global _APPROVE_FAIL
    _APPROVE_FAIL += 1

def inc_reject() -> None:
    global _REJECT
    _REJECT += 1

def inc_scan_eval() -> None:
    global _SCAN_EVALS
    _SCAN_EVALS += 1

def inc_scan_passed() -> None:
    global _SCAN_PASSED
    _SCAN_PASSED += 1

def inc_scan_blocked() -> None:
    global _SCAN_BLOCKED
    _SCAN_BLOCKED += 1

# -------------------- Lightweight Histograms --------------------
# קוביות קבועות מראש (ENV-override אופציונלי, CSV)
def _csv_floats(env: str, default: List[float]) -> List[float]:
    s = os.getenv(env, "").strip()
    if not s:
        return default[:]
    out: List[float] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except Exception:
            pass
    out = sorted(set(out))
    return out if out else default[:]

HTTP_LATENCY_BUCKETS = _csv_floats("HTTP_LATENCY_BUCKETS", [0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0])
TP1_TIME_BUCKETS     = _csv_floats("TP1_TIME_BUCKETS",     [30, 60, 120, 300, 600, 1200, 3600])
SLIP_BPS_BUCKETS     = _csv_floats("SLIP_BPS_BUCKETS",     [1, 2, 5, 10, 20, 50, 100])

# מצטברים בסגנון Prometheus: bucket_le (<=), sum, count
_http_lat_buckets: Dict[float, int] = {b:0 for b in HTTP_LATENCY_BUCKETS}
_http_lat_inf: int = 0
_http_lat_sum: float = 0.0
_http_lat_count: int = 0

_tp1_time_buckets: Dict[float, int] = {b:0 for b in TP1_TIME_BUCKETS}
_tp1_time_inf: int = 0
_tp1_time_sum: float = 0.0
_tp1_time_count: int = 0

_slip_bps_buckets: Dict[float, int] = {b:0 for b in SLIP_BPS_BUCKETS}
_slip_bps_inf: int = 0
_slip_bps_sum: float = 0.0
_slip_bps_count: int = 0

def _observe_into_buckets(value: float, buckets: Dict[float,int], inf_ref: str) -> None:
    # cumulative increment: לכל bucket שה־le שלו >= value, נעלה ב־1
    # אבל לשמירה על O(#buckets) קטן, נעלה רק בדלי הראשון הגדל־שווה — ונשתמש בייצוג non-cumulative ביצוא.
    # כדי להתאים ל־Prometheus, נכפיל לוגית ביצוא (נבנה cumulative שם).
    # כאן: נסמן רק את הדלי הראשון שמכסה את הערך.
    for b in sorted(buckets.keys()):
        if value <= b:
            buckets[b] += 1
            return
    # אם גדול מכל הדליים — נחשב ב־+Inf
    if inf_ref == "http":
        global _http_lat_inf
        _http_lat_inf += 1
    elif inf_ref == "tp1":
        global _tp1_time_inf
        _tp1_time_inf += 1
    elif inf_ref == "slip":
        global _slip_bps_inf
        _slip_bps_inf += 1

def observe_http_latency(seconds: float) -> None:
    global _http_lat_sum, _http_lat_count
    try:
        v = float(seconds)
    except Exception:
        return
    if v < 0: 
        return
    _http_lat_sum += v
    _http_lat_count += 1
    _observe_into_buckets(v, _http_lat_buckets, "http")

def observe_time_to_tp1(seconds: float) -> None:
    global _tp1_time_sum, _tp1_time_count
    try:
        v = float(seconds)
    except Exception:
        return
    if v < 0:
        return
    _tp1_time_sum += v
    _tp1_time_count += 1
    _observe_into_buckets(v, _tp1_time_buckets, "tp1")

def observe_slip_bps(bps: float) -> None:
    global _slip_bps_sum, _slip_bps_count
    try:
        v = float(bps)
    except Exception:
        return
    if v < 0:
        return
    _slip_bps_sum += v
    _slip_bps_count += 1
    _observe_into_buckets(v, _slip_bps_buckets, "slip")

def get_metrics_snapshot() -> Dict[str, Any]:
    uptime = time.time() - _START_TIME
    if _HAS_PSUTIL:
        try:
            cpu = float(psutil.cpu_percent(interval=0.1))  # type: ignore
            mem = float(psutil.virtual_memory().percent)   # type: ignore
        except Exception:
            cpu, mem = None, None
    else:
        cpu, mem = None, None
    return {
        "version": os.getenv("ALGOGPT_VERSION", "unknown"),
        "uptime_sec": round(uptime, 1),
        "cpu_pct": cpu,
        "mem_pct": mem,
        "telegram_sent": _SENT_TELEGRAM,
        "telegram_failed": _FAILED_TELEGRAM,
        "approve_ok": _APPROVE_OK,
        "approve_fail": _APPROVE_FAIL,
        "reject": _REJECT,
        "scan_evals": _SCAN_EVALS,
        "scan_passed": _SCAN_PASSED,
        "scan_blocked": _SCAN_BLOCKED,
        "last_entry_score": _LAST_ENTRY_SCORE,
    }

def _render_histogram(name: str,
                      buckets: Dict[float,int],
                      inf_count: int,
                      _sum: float,
                      _count: int,
                      help_text: str,
                      unit: str = "") -> List[str]:
    lines = [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} histogram",
    ]
    # הפוך ל־cumulative בזמן הרינדור
    total = 0
    for b in sorted(buckets.keys()):
        total += buckets[b]
        le = f'{b:.6g}{unit}' if unit else f"{b:.6g}"
        lines.append(f'{name}_bucket{{le="{le}"}} {total}')
    total += inf_count
    lines.append(f'{name}_bucket{{le="+Inf"}} {total}')
    lines.append(f"{name}_sum {_sum:.6f}")
    lines.append(f"{name}_count {_count}")
    return lines

def render_prometheus_text() -> str:
    lines = [
        "# HELP algogpt_uptime_seconds Process uptime seconds.",
        "# TYPE algogpt_uptime_seconds gauge",
        f"algogpt_uptime_seconds {_START_TIME and (time.time() - _START_TIME):.1f}",
        "# HELP algogpt_telegram_sent_total Telegram messages sent.",
        "# TYPE algogpt_telegram_sent_total counter",
        f"algogpt_telegram_sent_total {_SENT_TELEGRAM}",
        "# HELP algogpt_telegram_failed_total Telegram messages failed.",
        "# TYPE algogpt_telegram_failed_total counter",
        f"algogpt_telegram_failed_total {_FAILED_TELEGRAM}",
        "# HELP algogpt_approve_ok_total Approvals executed successfully.",
        "# TYPE algogpt_approve_ok_total counter",
        f"algogpt_approve_ok_total {_APPROVE_OK}",
        "# HELP algogpt_approve_fail_total Approvals execution failures.",
        "# TYPE algogpt_approve_fail_total counter",
        f"algogpt_approve_fail_total {_APPROVE_FAIL}",
        "# HELP algogpt_reject_total Reject actions.",
        "# TYPE algogpt_reject_total counter",
        f"algogpt_reject_total {_REJECT}",
        "# HELP algogpt_scan_evals_total Checklist evaluations.",
        "# TYPE algogpt_scan_evals_total counter",
        f"algogpt_scan_evals_total {_SCAN_EVALS}",
        "# HELP algogpt_scan_passed_total Tickets passed checklist gate.",
        "# TYPE algogpt_scan_passed_total counter",
        f"algogpt_scan_passed_total {_SCAN_PASSED}",
        "# HELP algogpt_scan_blocked_total Tickets blocked by checklist gate.",
        "# TYPE algogpt_scan_blocked_total counter",
        f"algogpt_scan_blocked_total {_SCAN_BLOCKED}",
    ]
    if _LAST_ENTRY_SCORE is not None:
        lines += [
            "# HELP algogpt_entry_quality_score_last Last computed pre-trade entry score (0..10).",
            "# TYPE algogpt_entry_quality_score_last gauge",
            f"algogpt_entry_quality_score_last {_LAST_ENTRY_SCORE:.3f}",
        ]

    # histograms
    lines += _render_histogram(
        "http_request_latency_seconds",
        _http_lat_buckets, _http_lat_inf, _http_lat_sum, _http_lat_count,
        "HTTP request latency in seconds."
    )
    lines += _render_histogram(
        "time_to_tp1_seconds",
        _tp1_time_buckets, _tp1_time_inf, _tp1_time_sum, _tp1_time_count,
        "Time until first take-profit in seconds."
    )
    lines += _render_histogram(
        "slip_realized_bps",
        _slip_bps_buckets, _slip_bps_inf, _slip_bps_sum, _slip_bps_count,
        "Realized slippage in basis points."
    )

    lines.append("")  # trailing newline
    return "\n".join(lines)

__all__ = [
    "record_telegram_sent","record_telegram_failed","get_metrics_snapshot",
    "inc_approve_ok","inc_approve_fail","inc_reject",
    "inc_scan_eval","inc_scan_passed","inc_scan_blocked",
    "render_prometheus_text","set_last_entry_score","get_last_entry_score",
    # histograms observe API
    "observe_http_latency","observe_time_to_tp1","observe_slip_bps",
]

