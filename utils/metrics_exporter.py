# utils/metrics_exporter.py
from __future__ import annotations
from typing import Any, Optional
from prometheus_client import Counter, Gauge, Histogram

# ───────────────────────────────────────────────
# Trades / PnL
# ───────────────────────────────────────────────
trades_open_total = Gauge("algogpt_trades_open_total", "מספר פוזיציות פתוחות כרגע")
trades_closed_total = Counter("algogpt_trades_closed_total", "סה\"כ פוזיציות שנסגרו")
pnl_total = Gauge("algogpt_pnl_total_usdt", "PnL מצטבר (USDT)")

# TP / SL
tp_hits_total = Counter("algogpt_tp_hits_total", "כמה פעמים TP הופעל", ["level"])
sl_hits_total = Counter("algogpt_sl_hits_total", "כמה פעמים SL הופעל")
breakeven_moves_total = Counter("algogpt_breakeven_moves_total", "SL הוזז ל-BE")
trailing_moves_total = Counter("algogpt_trailing_moves_total", "SL הוזז ע\"י Trailing")

# Approvals
approvals_total = Counter("algogpt_approvals_total", "מספר אישורים/דחיות", ["status"])

# AI
ai_requests_total = Counter("algogpt_ai_requests_total", "סה\"כ בקשות ל-AI", ["status"])
ai_latency_seconds = Histogram(
    "algogpt_ai_latency_seconds", "לטנסי קריאות AI", buckets=(0.2, 0.5, 1, 2, 3, 5, 10)
)

# ───────────────────────────────────────────────
# API (HTTP)
# ───────────────────────────────────────────────
api_requests_total = Counter(
    "algogpt_api_requests_total", "סה\"כ בקשות API", ["path", "method", "status"]
)
api_latency_seconds = Histogram(
    "algogpt_api_latency_seconds",
    "לטנסי API לפי נתיב",
    ["path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
api_5xx_total = Counter("algogpt_api_5xx_total", "סה\"כ שגיאות API 5xx")
api_response_bytes_total = Counter(
    "algogpt_api_response_bytes_total", "סך כל הבייטים שנשלחו בתגובות API"
)

# Executor/Grid toggles
auto_executor_enabled = Gauge("algogpt_auto_executor_enabled", "Auto Executor (1=on,0=off)")
grid_enabled = Gauge("algogpt_grid_enabled", "Grid מצב (1=on,0=off)")

# Telegram
telegram_sent_total = Counter("algogpt_telegram_messages_sent_total", "מספר הודעות שנשלחו")
telegram_failed_total = Counter("algogpt_telegram_messages_failed_total", "מספר הודעות שנכשלו")


# ───────────────────────────────────────────────
# Helpers (תאימות מלאה לאחור + קדימה)
# ───────────────────────────────────────────────

def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default

def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default

def record_trade_open(count_open: int) -> None:
    trades_open_total.set(int(count_open))

def record_trade_close() -> None:
    trades_closed_total.inc()

def record_pnl(v_usdt: float) -> None:
    pnl_total.set(float(v_usdt))

def record_tp_hit(level: str) -> None:
    tp_hits_total.labels(level=level).inc()

def record_sl_hit() -> None:
    sl_hits_total.inc()

def record_breakeven() -> None:
    breakeven_moves_total.inc()

def record_trailing() -> None:
    trailing_moves_total.inc()

def record_approval(status: str) -> None:
    approvals_total.labels(status=status).inc()

def record_ai_call(status: str = "ok", latency: Optional[float] = None, **kwargs: Any) -> None:
    """
    תאימות: record_ai_call(status, lat) הישן נתמך.
    kwargs: יכול לכלול lat/latency/duration וכו'.
    """
    lat = latency
    if lat is None:
        lat = kwargs.get("lat")
    if lat is None:
        lat = kwargs.get("duration") or kwargs.get("duration_s")
    lat = _as_float(lat, 0.0)

    ai_requests_total.labels(status=status).inc()
    if lat > 0:
        ai_latency_seconds.observe(lat)

def record_api_request(*args: Any, **kwargs: Any) -> None:
    """
    תאימות מלאה:
      ישן (positional):  record_api_request(path, method, status, lat)
      חדש (kwargs):      record_api_request(path=..., method=..., status_code=..., latency=..., bytes_out=...)
    שדות נוספים/לא מוכרים — יתעלמו.
    """
    path: str
    method: str
    status: int
    latency_s: float

    if args:
        # legacy positional order: path, method, status, lat
        path = str(args[0]) if len(args) > 0 else kwargs.get("path", "unknown")
        method = str(args[1]) if len(args) > 1 else kwargs.get("method", "GET")
        status = _as_int(args[2] if len(args) > 2 else kwargs.get("status"))
        latency_s = _as_float(args[3] if len(args) > 3 else kwargs.get("lat"))
        if latency_s == 0.0:
            latency_s = _as_float(kwargs.get("latency") or kwargs.get("duration") or kwargs.get("duration_s"))
    else:
        path = str(kwargs.get("path") or kwargs.get("url_path") or kwargs.get("endpoint") or "unknown")
        method = str(kwargs.get("method") or kwargs.get("http_method") or "GET")
        status = _as_int(kwargs.get("status") or kwargs.get("status_code") or kwargs.get("code"))
        latency_s = _as_float(kwargs.get("latency") or kwargs.get("lat") or kwargs.get("duration") or kwargs.get("duration_s"))

    # record
    api_requests_total.labels(path=path, method=method, status=str(status)).inc()
    if latency_s > 0:
        api_latency_seconds.labels(path=path).observe(latency_s)
    if status >= 500:
        api_5xx_total.inc()

    # optional bytes metric
    bytes_out = kwargs.get("bytes_out") or kwargs.get("response_bytes") or kwargs.get("size")
    if bytes_out is not None:
        api_response_bytes_total.inc(_as_int(bytes_out, 0))

def set_auto_executor(on: bool) -> None:
    auto_executor_enabled.set(1 if on else 0)

def set_grid(on: bool) -> None:
    grid_enabled.set(1 if on else 0)

def record_telegram_sent() -> None:
    telegram_sent_total.inc()

def record_telegram_failed() -> None:
    telegram_failed_total.inc()






