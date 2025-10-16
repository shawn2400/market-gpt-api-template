# -*- coding: utf-8 -*-
from __future__ import annotations
import time
import os
from typing import Dict, Any

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
_LAST_ENTRY_SCORE = None  # type: ignore

def set_last_entry_score(val: float) -> None:
    global _LAST_ENTRY_SCORE
    try:
        _LAST_ENTRY_SCORE = float(val)
    except Exception:
        _LAST_ENTRY_SCORE = None

def record_telegram_sent() -> None:
    global _SENT_TELEGRAM
    _SENT_TELEGRAM += 1

def record_telegram_failed() -> None:
    global _FAILED_TELEGRAM
    _FAILED_TELEGRAM += 1

def inc_approve_ok():
    global _APPROVE_OK; _APPROVE_OK += 1

def inc_approve_fail():
    global _APPROVE_FAIL; _APPROVE_FAIL += 1

def inc_reject():
    global _REJECT; _REJECT += 1

def inc_scan_eval():
    global _SCAN_EVALS; _SCAN_EVALS += 1

def inc_scan_passed():
    global _SCAN_PASSED; _SCAN_PASSED += 1

def inc_scan_blocked():
    global _SCAN_BLOCKED; _SCAN_BLOCKED += 1

def get_metrics_snapshot() -> Dict[str, Any]:
    uptime = time.time() - _START_TIME
    if _HAS_PSUTIL:
        try:
            cpu = float(psutil.cpu_percent(interval=0.1))
            mem = float(psutil.virtual_memory().percent)
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
    }

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
    lines.append("")  # trailing newline
    return "\n".join(lines)

__all__ = [
    "record_telegram_sent","record_telegram_failed","get_metrics_snapshot",
    "inc_approve_ok","inc_approve_fail","inc_reject",
    "inc_scan_eval","inc_scan_passed","inc_scan_blocked",
    "render_prometheus_text","set_last_entry_score",
]
