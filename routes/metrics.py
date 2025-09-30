# routes/metrics.py
from __future__ import annotations
import os, time
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Query
from prometheus_client import Counter, Gauge, REGISTRY

router = APIRouter(tags=["metrics"])

# ---------- Low-cardinality label policy ----------
def _allowlist_symbols() -> set:
    w = os.getenv("WATCHLIST", "BTCUSDT,ETHUSDT,SOLUSDT")
    return {x.strip().upper() for x in w.split(",") if x.strip()}

_ALLOWS = _allowlist_symbols()
_OTHER = "OTHER"

def _lbl_symbol(sym: Optional[str]) -> str:
    s = (sym or "").strip().upper()
    return s if (s and s in _ALLOWS) else _OTHER

def _lbl_side(side: Optional[str]) -> str:
    s = (side or "").strip().upper()
    return s if s in ("BUY", "SELL") else "NA"

def _lbl_flow(flow: Optional[str]) -> str:
    s = (flow or "").strip().upper()
    return s if s in ("MARKET", "HYBRID", "APPROVAL") else "NA"

# ---------- Prometheus metrics ----------
# approvals lifecycle
APPROVALS_CREATED     = Counter("approvals_created_total",  "Total approval tickets created")
APPROVALS_APPROVED    = Counter("approvals_approved_total", "Total approvals approved")
APPROVALS_REJECTED    = Counter("approvals_rejected_total", "Total approvals rejected")
APPROVALS_EXPIRED     = Counter("approvals_expired_total",  "Total approvals auto-expired")

# low-card aggregation by symbol/side (OTHER for non-allowlist)
APPROVALS_EXPIRED_BY_SYMBOL = Counter(
    "approvals_expired_by_symbol",
    "Expired approvals by symbol/side (low-card)",
    ["symbol", "side"],
)

# gc last-run metadata
APPROVALS_GC_LAST_RUN_TS   = Gauge("approvals_gc_last_run_ts",   "Last approvals-GC run UNIX ts")
APPROVALS_GC_LAST_EXPIRED  = Gauge("approvals_gc_last_expired",  "Last approvals-GC expired count")

# trade execution
TRADE_EXEC_REQUESTS = Counter("trade_execute_requests_total", "Trade execute requests", ["flow"])
TRADE_EXEC_OK       = Counter("trade_execute_ok_total",       "Successful trade executes", ["flow"])
TRADE_EXEC_FAIL     = Counter("trade_execute_fail_total",     "Failed trade executes", ["flow"])

# trade approval actions (APPROVAL plane; low-card labels)
TRADE_APPROVAL_ACTIONS = Counter(
    "trade_approval_actions_total",
    "Trade approval actions (approve/reject) with result state",
    ["flow", "action", "result"],  # flow fixed to APPROVAL; action ∈ {APPROVE, REJECT}; result ∈ {OK, FAIL}
)

# ---------- Public helpers ----------
def record_approval_created() -> None:
    APPROVALS_CREATED.inc()

def record_approval_approved() -> None:
    APPROVALS_APPROVED.inc()

def record_approval_rejected() -> None:
    APPROVALS_REJECTED.inc()

def record_approval_expired(symbol: Optional[str], side: Optional[str]) -> None:
    APPROVALS_EXPIRED.inc()
    APPROVALS_EXPIRED_BY_SYMBOL.labels(_lbl_symbol(symbol), _lbl_side(side)).inc()

def record_trade_request(flow: Optional[str]) -> None:
    TRADE_EXEC_REQUESTS.labels(_lbl_flow(flow)).inc()

def record_trade_ok(flow: Optional[str]) -> None:
    TRADE_EXEC_OK.labels(_lbl_flow(flow)).inc()

def record_trade_fail(flow: Optional[str]) -> None:
    TRADE_EXEC_FAIL.labels(_lbl_flow(flow)).inc()

def record_trade_approval(action: str, ok: bool) -> None:
    a = "APPROVE" if str(action).strip().upper() == "APPROVE" else "REJECT"
    r = "OK" if ok else "FAIL"
    TRADE_APPROVAL_ACTIONS.labels("APPROVAL", a, r).inc()

def record_gc_last_run(now_ts: Optional[float] = None, expired_count: Optional[int] = None) -> None:
    if now_ts is None:
        now_ts = time.time()
    APPROVALS_GC_LAST_RUN_TS.set(float(now_ts))
    if expired_count is not None:
        APPROVALS_GC_LAST_EXPIRED.set(float(expired_count))

# ---------- JSON snapshot ----------
def _scrape_snapshot(prefix: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns a simple JSON of current counters/gauges (optionally filtered by name prefix).
    Not a replacement for Prometheus scrape; meant for dashboards / quick debug.
    """
    out: Dict[str, Any] = {}
    try:
        for metric in REGISTRY.collect():
            name = metric.name
            if prefix and not name.startswith(prefix):
                continue
            series: List[Dict[str, Any]] = []
            for sample in metric.samples:
                s_name, s_labels, s_value, *_ = sample
                if not s_name.startswith(name):
                    continue
                row = {"value": s_value}
                if s_labels:
                    row["labels"] = s_labels
                series.append(row)
            out[name] = series
    except Exception as e:
        out = {"error": f"scrape_failed: {e}"}
    return out

@router.get("/metrics-json", summary="JSON metrics snapshot (optionally filter by ?prefix=)")
async def metrics_json(prefix: Optional[str] = Query(default=None, description="filter metrics by name prefix")):
    return _scrape_snapshot(prefix=prefix)

@router.get("/metrics/health", summary="Basic metrics health")
async def metrics_health():
    return {
        "ok": True,
        "approvals": {
            "created": _sum_metric("approvals_created_total"),
            "approved": _sum_metric("approvals_approved_total"),
            "rejected": _sum_metric("approvals_rejected_total"),
            "expired":  _sum_metric("approvals_expired_total"),
            "gc_last_run_ts": _last_gauge("approvals_gc_last_run_ts"),
            "gc_last_expired": _last_gauge("approvals_gc_last_expired"),
        },
        "trade_exec": {
            "requests_total": _sum_metric("trade_execute_requests_total"),
            "ok_total":       _sum_metric("trade_execute_ok_total"),
            "fail_total":     _sum_metric("trade_execute_fail_total"),
            "approvals_actions_total": _sum_metric("trade_approval_actions_total"),
        },
    }

# ---------- labels/allowlist export ----------
@router.get("/metrics/labels", summary="Current low-cardinality label sets (allowlist + OTHER)")
async def metrics_labels():
    """
    חשיפה דינמית ל־UI:
      - watchlist: רשימת סימבולים שמוגדרים ב-WATCHLIST (לאותם counters עם low-cardinality)
      - other: התווית שמשתמשים בה עבור כל סימבול שלא ב-allowlist
      - env_watchlist: המחרוזת הגולמית מ-WATCHLIST (לניטור תצורה)
    """
    return {
        "ok": True,
        "watchlist": sorted(list(_ALLOWS)),
        "other": _OTHER,
        "env_watchlist": os.getenv("WATCHLIST", "BTCUSDT,ETHUSDT,SOLUSDT"),
        "ts": int(time.time()),
    }

# ---------- tiny helpers ----------
def _sum_metric(name: str) -> float:
    total = 0.0
    try:
        for m in REGISTRY.collect():
            if m.name != name:
                continue
            for s in m.samples:
                if s.name == name:
                    total += float(s.value)
    except Exception:
        pass
    return total

def _last_gauge(name: str) -> Optional[float]:
    try:
        for m in REGISTRY.collect():
            if m.name != name:
                continue
            vals = [float(s.value) for s in m.samples if s.name == name]
            if vals:
                return vals[-1]
    except Exception:
        pass
    return None




