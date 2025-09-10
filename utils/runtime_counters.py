# utils/runtime_counters.py
from __future__ import annotations
import os, time, threading, math
from collections import deque
from typing import Dict, Any, Optional, List, Tuple

_ws_lock = threading.Lock()
_exec_lock = threading.Lock()

# ===== ENV =====
_WS_ALPHA = float(os.getenv("WS_LAT_EWMA_ALPHA", "0.2"))
_EXEC_ALPHA = float(os.getenv("EXEC_TICK_EWMA_ALPHA", "0.2"))
_STATUS_PRICE_TTL_ALERT = int(os.getenv("STATUS_PRICE_TTL_ALERT_SEC", "10"))
_EXEC_TIMEOUT_BURST_ALERT = int(os.getenv("EXEC_TIMEOUT_BURST_ALERT", "3"))
_OPS_TICK_ENABLE = os.getenv("OPS_TICK_ENABLE", "1").lower() in ("1","true","on","yes")
_PRICE_DRIFT_BPS_ALERT = float(os.getenv("PRICE_DRIFT_BPS_ALERT", "25"))
_HEALTH_SYMBOLS = [s.strip().upper() for s in os.getenv("HEALTH_SYMBOLS","BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]

# ===== EWMA helpers =====
def _ewma(prev: float, x: float, alpha: float) -> float:
    if prev <= 0: return float(x)
    return (1.0 - alpha) * prev + alpha * float(x)

# ===== WS state =====
_ws_state: Dict[str, Any] = {
    "ewma_lat_ms": 0.0,
    "reconnects": 0,
    "last_event_ts": 0.0,
    "ttl_sec": 0.0,
    "up": 0,
}

# ===== EXEC state =====
_exec_tick_ms: deque = deque(maxlen=2000)
_exec_state: Dict[str, Any] = {
    "ewma_ms": 0.0,
    "timeouts_last_60s": 0,
    "batch_timeouts_total": 0,
    "trades_sent_60s": 0,
    "no_trade_streak": 0,
    "current_interval": 0,
    "last_tick_ts": 0.0,
}

_time_buckets: deque = deque(maxlen=1000)  # ts of timeouts
_trade_buckets: deque = deque(maxlen=2000) # ts of sent trades

# ===== Ops flags =====
_degrade_active = False  # במצב זה: מחמירים שערים, מקשיחים מינוף
_last_ops_eval = 0.0

# ===== Price TTL helpers (optional WS cache) =====
def _price_ttl_sec() -> float:
    # Optional dependency on ws_fallback; fallback to 0 if not available.
    try:
        from utils import ws_fallback
        # אם יש פונקציה ייעודית:
        if hasattr(ws_fallback, "get_global_ttl_sec"):
            return float(ws_fallback.get_global_ttl_sec() or 0.0)
        # אחרת ננסה על אחד הסימבולים
        now = time.time()
        if hasattr(ws_fallback, "get_last_update_ts"):
            ts = ws_fallback.get_last_update_ts()
            return float(now - float(ts or 0.0)) if ts else 0.0
    except Exception:
        pass
    return 0.0

# ===== Price Drift (Mark vs Index) =====
def _try_get_index_price(symbol: str) -> Optional[float]:
    try:
        # אם תוסיף פונקציה רשמית בעתיד (למשל futures_index_price) — נשתמש בה מיד
        from utils.binance_client import futures_index_price  # type: ignore
        try:
            return float(futures_index_price(symbol) or 0.0)  # type: ignore
        except Exception:
            return None
    except Exception:
        return None

def _get_mark_price(symbol: str) -> Optional[float]:
    try:
        from utils.binance_client import futures_mark_price
        return float(futures_mark_price(symbol) or 0.0)
    except Exception:
        return None

def _drift_bps(mark: float, index: float) -> float:
    try:
        if index <= 0 or mark <= 0:
            return 0.0
        return abs(mark - index) / index * 10000.0
    except Exception:
        return 0.0

_price_drift_alerts: deque = deque(maxlen=100)  # (ts, symbol, bps)

def _scan_price_drift() -> Dict[str, Any]:
    worst = {"symbol": None, "bps": 0.0}
    if _PRICE_DRIFT_BPS_ALERT <= 0:
        return {"worst": worst, "alerts": 0}
    alerts_new = 0
    for s in _HEALTH_SYMBOLS:
        mark = _get_mark_price(s)
        idx = _try_get_index_price(s)
        if not mark or not idx:
            continue
        bps = _drift_bps(mark, idx)
        if bps > (worst["bps"] or 0.0):
            worst = {"symbol": s, "bps": round(bps, 2)}
        if bps >= _PRICE_DRIFT_BPS_ALERT:
            _price_drift_alerts.append((time.time(), s, bps))
            alerts_new += 1
    return {"worst": worst, "alerts": alerts_new}

# ===== Public WS notifiers (optional to call from ws layer) =====
def ws_note_event(latency_ms: Optional[float] = None) -> None:
    with _ws_lock:
        if latency_ms is not None:
            _ws_state["ewma_lat_ms"] = _ewma(_ws_state["ewma_lat_ms"], float(latency_ms), _WS_ALPHA)
        _ws_state["last_event_ts"] = time.time()
        _ws_state["ttl_sec"] = _price_ttl_sec()

def ws_note_reconnect() -> None:
    with _ws_lock:
        _ws_state["reconnects"] = int(_ws_state.get("reconnects", 0)) + 1
        _ws_state["up"] = 0

def ws_note_up(up: bool) -> None:
    with _ws_lock:
        _ws_state["up"] = 1 if up else 0

def get_ws_status() -> Dict[str, Any]:
    with _ws_lock:
        st = dict(_ws_state)
    st["ttl_sec"] = max(st.get("ttl_sec", 0.0), _price_ttl_sec())
    st["ttl_alert"] = bool(_STATUS_PRICE_TTL_ALERT and st["ttl_sec"] >= _STATUS_PRICE_TTL_ALERT)
    st["ts"] = int(time.time())
    return st

# ===== Executor notifiers (from auto_executor) =====
def exec_on_trade_sent(symbol: str) -> None:
    now = time.time()
    _trade_buckets.append(now)

def exec_on_batch_timeout() -> None:
    _time_buckets.append(time.time())

def exec_on_tick_stop(dt_ms: float, current_interval: int, no_trade_streak: int) -> None:
    now = time.time()
    with _exec_lock:
        _exec_state["ewma_ms"] = _ewma(_exec_state["ewma_ms"], float(dt_ms), _EXEC_ALPHA)
        _exec_state["last_tick_ts"] = now
        _exec_state["no_trade_streak"] = int(no_trade_streak)
        _exec_state["current_interval"] = int(current_interval)
        _exec_tick_ms.append(float(dt_ms))

    # timeouts in last 60s
    cutoff = now - 60.0
    while _time_buckets and _time_buckets[0] < cutoff:
        _time_buckets.popleft()
    _exec_state["timeouts_last_60s"] = len(_time_buckets)

    # trades sent last 60s
    while _trade_buckets and _trade_buckets[0] < cutoff:
        _trade_buckets.popleft()
    _exec_state["trades_sent_60s"] = len(_trade_buckets)

def _pctl(values: List[float], p: float) -> float:
    if not values: return 0.0
    s = sorted(values)
    k = max(0, min(len(s)-1, int(round((p/100.0)*(len(s)-1)))))
    return float(s[k])

def get_executor_status() -> Dict[str, Any]:
    with _exec_lock:
        ms = list(_exec_tick_ms)
        st = dict(_exec_state)
    p95 = _pctl(ms, 95.0)
    p99 = _pctl(ms, 99.0)
    st.update({
        "p50_ms": _pctl(ms, 50.0),
        "p95_ms": p95,
        "p99_ms": p99,
        "count": len(ms),
    })
    st["degrade_active"] = bool(_degrade_active)
    st["ts"] = int(time.time())
    return st

# ===== Ops logic (called every executor tick) =====
def _should_degrade() -> bool:
    # קריטריונים פשוטים: TTL גבוה, פרצי timeouts, או P99 חריג
    ttl = _price_ttl_sec()
    timeouts = int(_exec_state.get("timeouts_last_60s", 0))
    ewma_ms = float(_exec_state.get("ewma_ms", 0.0))
    # אם אין דגימות — אל נכנס
    if ewma_ms <= 0:
        return False
    cond_ttl = bool(_STATUS_PRICE_TTL_ALERT and ttl >= _STATUS_PRICE_TTL_ALERT)
    cond_to = bool(_EXEC_TIMEOUT_BURST_ALERT and timeouts >= _EXEC_TIMEOUT_BURST_ALERT)
    return cond_ttl or cond_to

def ops_is_degraded() -> bool:
    return bool(_degrade_active)

def ops_tick_safe() -> None:
    """
    נקרא בסוף כל tick של הסורק.
    - מחשב TTL
    - בודק Price-Drift (אם יש פונקציית index)
    - מעדכן דגל degrade_active אוטומטי
    - ניתן להדליק כאן גם התראות לטלגרם (TTL/Timeout burst) — בהמשך
    """
    if not _OPS_TICK_ENABLE:
        return
    now = time.time()
    global _degrade_active, _last_ops_eval
    # עדכון TTL בסטטוס WS
    with _ws_lock:
        _ws_state["ttl_sec"] = _price_ttl_sec()

    # Price drift scan
    _ = _scan_price_drift()

    # Evaluate degrade only פעם ב-3ש׳׳
    if now - _last_ops_eval > 3.0:
        _degrade_active = _should_degrade()
        _last_ops_eval = now



