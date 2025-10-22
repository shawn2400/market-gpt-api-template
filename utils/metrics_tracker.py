# -*- coding: utf-8 -*-
from __future__ import annotations
import time
import os
import functools
import inspect
from contextlib import asynccontextmanager, contextmanager
from typing import Dict, Any, Optional, List, Callable

from prometheus_client import Counter, Summary, Histogram
import os  # (נשאר גם כאן לצורך שימוש פנימי בהמשך)

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

# New: approvals created
_APPROVALS_CREATED = 0

# New: שלב 5 – מונים לניהול TP
_TP_MERGE = 0
_TP_REARM = 0
_TP_NUDGED = 0

# New: שלב 4 – manage-once placement/fail (נדרש ע"י tp_helper)
_MANAGE_ONCE_PLACED = 0
_MANAGE_ONCE_FAILED = 0

# New: שלב 6 – Time-Stop ו־Structural SL
_TIME_STOP_KEEP = 0
_TIME_STOP_MOVE_BE = 0
_STRUCT_SL_APPLIED = 0

# last computed checklist score (gauge)
_LAST_ENTRY_SCORE: Optional[float] = None

# New: last slip estimate bps (gauge)
_LAST_SLIP_ESTIMATE_BPS: Optional[float] = None

# New: gauges "אחרונים" לשלב 4
_LAST_CALLBACK_RATE: Optional[float] = None
_LAST_BE_DISTANCE_BPS: Optional[float] = None
_LAST_TP_LADDERS: Optional[int] = None

def inc_event(*a, **k) -> None:
    """שומר תאימות לאזכורי inc_event היסטוריים (no-op)."""
    return None

def set_last_entry_score(val: Optional[float]) -> None:
    global _LAST_ENTRY_SCORE
    try:
        _LAST_ENTRY_SCORE = None if val is None else float(val)
    except Exception:
        _LAST_ENTRY_SCORE = None

def get_last_entry_score() -> Optional[float]:
    return _LAST_ENTRY_SCORE

def set_last_slip_estimate_bps(val: Optional[float]) -> None:
    global _LAST_SLIP_ESTIMATE_BPS
    try:
        _LAST_SLIP_ESTIMATE_BPS = None if val is None else float(val)
    except Exception:
        _LAST_SLIP_ESTIMATE_BPS = None

def get_last_slip_estimate_bps() -> Optional[float]:
    return _LAST_SLIP_ESTIMATE_BPS

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

def inc_approvals_created() -> None:
    global _APPROVALS_CREATED
    _APPROVALS_CREATED += 1

# שלב 5 – Counters
def inc_tp_merge() -> None:
    global _TP_MERGE
    _TP_MERGE += 1

def inc_tp_rearm() -> None:
    global _TP_REARM
    _TP_REARM += 1

def inc_tp_nudged() -> None:
    global _TP_NUDGED
    _TP_NUDGED += 1

# שלב 4 – manage-once counters (נדרש ע"י tp_helper)
def inc_manage_once_placed() -> None:
    global _MANAGE_ONCE_PLACED
    _MANAGE_ONCE_PLACED += 1

def inc_manage_once_failed() -> None:
    global _MANAGE_ONCE_FAILED
    _MANAGE_ONCE_FAILED += 1

# שלב 6 – Time-Stop & Structural SL
def inc_time_stop_keep() -> None:
    """נספר כש־time-stop החליט 'להישאר' (keep)"""
    global _TIME_STOP_KEEP
    _TIME_STOP_KEEP += 1

def inc_time_stop_move_be() -> None:
    """נספר כש־time-stop החליט 'להזיז ל־BE' (move to break-even)"""
    global _TIME_STOP_MOVE_BE
    _TIME_STOP_MOVE_BE += 1

def inc_struct_sl_applied() -> None:
    """נספר כשה־Structural SL באמת השפיע (merged_stop != be_price)"""
    global _STRUCT_SL_APPLIED
    _STRUCT_SL_APPLIED += 1

# -------------------- Prometheus metrics (Realtime manage) --------------------
POS_BE_TRIGGER = Counter(
    "pos_live_manage_be_trigger_total",
    "Count of BE triggers",
    ["symbol", "side", "timeframe", "market"],
)
POS_GRACE_VIOLATION = Counter(
    "pos_live_manage_grace_violation_total",
    "Count of Grace MAE cap violations",
    ["symbol", "side", "timeframe", "market"],
)
POS_TRAIL_ADJUST = Counter(
    "pos_live_manage_trail_adjust_total",
    "Count of trail adjustments",
    ["symbol", "side", "timeframe", "market"],
)

_SL_BPS_BUCKETS = (
    0.25, 0.5, 1.0, 1.5, 2.0,
    3.0, 5.0, 8.0, 13.0, 21.0, 34.0, 55.0
)
POS_SL_STEP_BPS = Histogram(
    "pos_live_manage_sl_step_bps",
    "SL step size (basis points of last/target price)",
    ["symbol", "side", "timeframe", "market"],
    buckets=_SL_BPS_BUCKETS,
)

_ATR_PCT_BUCKETS = (
    0.0005, 0.0010, 0.0020, 0.0030, 0.0050,
    0.0080, 0.0120, 0.0150, 0.0200, 0.0300, 0.0500
)
POS_ATR_PCT = Histogram(
    "pos_live_manage_atr_pct",
    "ATR as fraction of price (e.g., 0.012 = 1.2%)",
    ["symbol", "timeframe", "market"],
    buckets=_ATR_PCT_BUCKETS,
)

# -------------------- Lightweight Histograms --------------------
def _csv_floats(env: str, default: List[float]) -> List[float]:
    s = (os.getenv(env, "") or "").strip()
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

_http_lat_buckets: Dict[float, int] = {b: 0 for b in HTTP_LATENCY_BUCKETS}
_http_lat_inf: int = 0
_http_lat_sum: float = 0.0
_http_lat_count: int = 0

_tp1_time_buckets: Dict[float, int] = {b: 0 for b in TP1_TIME_BUCKETS}
_tp1_time_inf: int = 0
_tp1_time_sum: float = 0.0
_tp1_time_count: int = 0

_slip_bps_buckets: Dict[float, int] = {b: 0 for b in SLIP_BPS_BUCKETS}
_slip_bps_inf: int = 0
_slip_bps_sum: float = 0.0
_slip_bps_count: int = 0

def _observe_into_buckets(value: float, buckets: Dict[float,int], inf_ref: str) -> None:
    for b in sorted(buckets.keys()):
        if value <= b:
            buckets[b] += 1
            return
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

# --- Gauges “אחרונים” לשלב 4/5 (פשוטים, נמוכי-קרדינליות) ---
def observe_callback_rate(v: float) -> None:
    global _LAST_CALLBACK_RATE
    try:
        _LAST_CALLBACK_RATE = float(v)
    except Exception:
        _LAST_CALLBACK_RATE = None

def observe_be_distance_bps(v: float) -> None:
    global _LAST_BE_DISTANCE_BPS
    try:
        _LAST_BE_DISTANCE_BPS = float(v)
    except Exception:
        _LAST_BE_DISTANCE_BPS = None

def observe_tp_ladders(n: int) -> None:
    global _LAST_TP_LADDERS
    try:
        _LAST_TP_LADDERS = int(n)
    except Exception:
        _LAST_TP_LADDERS = None

# -------------------- Prometheus helpers (labels with tf/market) --------------------
def _df_tf() -> str:
    return os.getenv("DEFAULT_INTERVAL", os.getenv("ENTRY_SCORE_INTERVAL", "15m"))

def _df_mkt() -> str:
    return os.getenv("DEFAULT_MARKET", "futures").lower()

def observe_sl_step_bps(symbol: str, side: str, step_bps: float,
                        timeframe: str | None = None,
                        market: str | None = None) -> None:
    """
    שלח גודל צעד SL בהזזה נתונה ל-Histogram (ב-bps).
    """
    try:
        POS_SL_STEP_BPS.labels(
            symbol=str(symbol).upper(),
            side=str(side).upper(),
            timeframe=(timeframe or _df_tf()),
            market=(market or _df_mkt()),
        ).observe(float(step_bps))
    except Exception:
        pass

def observe_atr_pct(symbol: str, atr_frac: float,
                    timeframe: str | None = None,
                    market: str | None = None) -> None:
    """
    שלח ATR/Price (חלק עשרוני, לדוגמה 0.012 = 1.2%) להיסטוגרמה.
    """
    try:
        POS_ATR_PCT.labels(
            symbol=str(symbol).upper(),
            timeframe=(timeframe or _df_tf()),
            market=(market or _df_mkt()),
        ).observe(float(atr_frac))
    except Exception:
        pass

# -------------------- Observe (ctx + decorator) --------------------
@contextmanager
def observe_http_ctx(name: str = "io", labels: Optional[Dict[str,str]] = None):
    """
    שימוש:
      with observe_http_ctx("binance", {"route":"/scan"}):
          ... IO ...
    מודד latency ושופך להיסטוגרמה הגנרית (דלי נמוך קרדינליות).
    """
    _ = name, labels  # שמור לעתיד
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        observe_http_latency(dt)

@asynccontextmanager
async def observe_http_ctx_async(name: str = "io", labels: Optional[Dict[str,str]] = None):
    _ = name, labels
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        observe_http_latency(dt)

def observe_http(name: str = "io", include_labels: Optional[List[str]] = None):
    include_labels = include_labels or []

    def _decorator(fn: Callable[..., Any]):
        is_async = inspect.iscoroutinefunction(fn)

        @functools.wraps(fn)
        async def _aw(*args, **kwargs):
            labels: Dict[str,str] = {}
            for k in include_labels:
                v = kwargs.get(k, None)
                if v is None and args:
                    try:
                        sig = inspect.signature(fn)
                        names = list(sig.parameters.keys())
                        if k in names:
                            idx = names.index(k)
                            if idx < len(args):
                                v = args[idx]
                    except Exception:
                        pass
                if v is not None:
                    labels[k] = str(v)
            async with observe_http_ctx_async(name=name, labels=labels):
                return await fn(*args, **kwargs)

        @functools.wraps(fn)
        def _sw(*args, **kwargs):
            labels: Dict[str,str] = {}
            for k in include_labels:
                if k in kwargs and kwargs[k] is not None:
                    labels[k] = str(kwargs[k])
            with observe_http_ctx(name=name, labels=labels):
                return fn(*args, **kwargs)

        return _aw if is_async else _sw

    return _decorator

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
        "approvals_created": _APPROVALS_CREATED,
        "tp_merged": _TP_MERGE,
        "tp_rearmed": _TP_REARM,
        "tp_nudged": _TP_NUDGED,
        "manage_once_placed": _MANAGE_ONCE_PLACED,
        "manage_once_failed": _MANAGE_ONCE_FAILED,
        "time_stop_keep": _TIME_STOP_KEEP,
        "time_stop_move_be": _TIME_STOP_MOVE_BE,
        "struct_sl_applied": _STRUCT_SL_APPLIED,
        "last_entry_score": _LAST_ENTRY_SCORE,
        "last_slip_estimate_bps": _LAST_SLIP_ESTIMATE_BPS,
        "last_callback_rate": _LAST_CALLBACK_RATE,
        "last_be_distance_bps": _LAST_BE_DISTANCE_BPS,
        "last_tp_ladders": _LAST_TP_LADDERS,
    }

def _render_histogram(name: str,
                      buckets: Dict[float,int],
                      inf_count: int,
                      _sum: float,
                      _count: int,
                      help_text: str) -> List[str]:
    lines = [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} histogram",
    ]
    total = 0
    for b in sorted(buckets.keys()):
        total += buckets[b]
        # Prometheus מצפה ל־le מספרי – נשמור בלי יחידות
        lines.append(f'{name}_bucket{{le="{b:.6g}"}} {total}')
    total += inf_count
    lines.append(f'{name}_bucket{{le="+Inf"}} {total}')
    lines.append(f"{name}_sum {float(_sum):.6f}")
    lines.append(f"{name}_count {int(_count)}")
    return lines

def render_prometheus_text() -> str:
    lines = [
        "# HELP algogpt_uptime_seconds Process uptime seconds.",
        "# TYPE algogpt_uptime_seconds gauge",
        f"algogpt_uptime_seconds {max(0.0, (time.time() - _START_TIME)):.1f}",
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
        "# HELP algogpt_approvals_created_total Approval tickets created.",
        "# TYPE algogpt_approvals_created_total counter",
        f"algogpt_approvals_created_total {_APPROVALS_CREATED}",
        "# HELP algogpt_tp_merge_total TP merges executed.",
        "# TYPE algogpt_tp_merge_total counter",
        f"algogpt_tp_merge_total {_TP_MERGE}",
        "# HELP algogpt_tp_rearm_total TP rearm actions executed.",
        "# TYPE algogpt_tp_rearm_total counter",
        f"algogpt_tp_rearm_total {_TP_REARM}",
        "# HELP algogpt_tp_nudged_total TP anti-stale nudges executed.",
        "# TYPE algogpt_tp_nudged_total counter",
        f"algogpt_tp_nudged_total {_TP_NUDGED}",
        "# HELP algogpt_manage_once_placed_total manage-once flows successfully placed.",
        "# TYPE algogpt_manage_once_placed_total counter",
        f"algogpt_manage_once_placed_total {_MANAGE_ONCE_PLACED}",
        "# HELP algogpt_manage_once_failed_total manage-once flows failed to place.",
        "# TYPE algogpt_manage_once_failed_total counter",
        f"algogpt_manage_once_failed_total {_MANAGE_ONCE_FAILED}",
        "# HELP algogpt_time_stop_keep_total Time-stop decisions to KEEP position.",
        "# TYPE algogpt_time_stop_keep_total counter",
        f"algogpt_time_stop_keep_total {_TIME_STOP_KEEP}",
        "# HELP algogpt_time_stop_move_be_total Time-stop decisions to MOVE to break-even.",
        "# TYPE algogpt_time_stop_move_be_total counter",
        f"algogpt_time_stop_move_be_total {_TIME_STOP_MOVE_BE}",
        "# HELP algogpt_struct_sl_applied_total Structural SL actually affected stop (merged != BE).",
        "# TYPE algogpt_struct_sl_applied_total counter",
        f"algogpt_struct_sl_applied_total {_STRUCT_SL_APPLIED}",
    ]
    if _LAST_ENTRY_SCORE is not None:
        lines += [
            "# HELP algogpt_entry_quality_score_last Last computed pre-trade entry score (0..10).",
            "# TYPE algogpt_entry_quality_score_last gauge",
            f"algogpt_entry_quality_score_last {float(_LAST_ENTRY_SCORE):.3f}",
        ]
    if _LAST_SLIP_ESTIMATE_BPS is not None:
        lines += [
            "# HELP algogpt_slip_estimate_bps_last Last estimated slip (bps) at ticket creation.",
            "# TYPE algogpt_slip_estimate_bps_last gauge",
            f"algogpt_slip_estimate_bps_last {float(_LAST_SLIP_ESTIMATE_BPS):.3f}",
        ]
    if _LAST_CALLBACK_RATE is not None:
        lines += [
            "# HELP algogpt_trailing_callback_rate_last Last computed trailing callback rate (percent).",
            "# TYPE algogpt_trailing_callback_rate_last gauge",
            f"algogpt_trailing_callback_rate_last {float(_LAST_CALLBACK_RATE):.3f}",
        ]
    if _LAST_BE_DISTANCE_BPS is not None:
        lines += [
            "# HELP algogpt_be_distance_bps_last Last computed BE distance from price (bps).",
            "# TYPE algogpt_be_distance_bps_last gauge",
            f"algogpt_be_distance_bps_last {float(_LAST_BE_DISTANCE_BPS):.3f}",
        ]
    if _LAST_TP_LADDERS is not None:
        lines += [
            "# HELP algogpt_tp_ladders_last Last number of TP ladders placed in manage-once.",
            "# TYPE algogpt_tp_ladders_last gauge",
            f"algogpt_tp_ladders_last {int(_LAST_TP_LADDERS)}",
        ]

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

    lines.append("")
    return "\n".join(lines)

__all__ = [
    "record_telegram_sent","record_telegram_failed","get_metrics_snapshot",
    "inc_approve_ok","inc_approve_fail","inc_reject",
    "inc_scan_eval","inc_scan_passed","inc_scan_blocked",
    "inc_approvals_created",
    "inc_tp_merge","inc_tp_rearm","inc_tp_nudged",
    "inc_manage_once_placed","inc_manage_once_failed",
    "inc_time_stop_keep","inc_time_stop_move_be","inc_struct_sl_applied",
    "render_prometheus_text","set_last_entry_score","get_last_entry_score",
    "set_last_slip_estimate_bps","get_last_slip_estimate_bps",
    "observe_http_latency","observe_time_to_tp1","observe_slip_bps",
    "observe_http_ctx","observe_http_ctx_async","observe_http",
    "observe_callback_rate","observe_be_distance_bps","observe_tp_ladders",
    "inc_event",
    # חדשים לפרומתאוס:
    "observe_sl_step_bps","observe_atr_pct",
]




