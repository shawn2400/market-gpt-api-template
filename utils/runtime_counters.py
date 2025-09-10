# utils/runtime_counters.py
from __future__ import annotations
import os, time, math, threading
from collections import deque
from typing import Dict, Any, Optional, List

# ===== Optional deps (don’t break if missing) =====
try:
    from utils.telegram_notifier import notify_error as _notify_err, notify_info as _notify_info
except Exception:
    async def _notify_err(*a, **k): return None
    async def _notify_info(*a, **k): return None

# Optional mark/index price funcs (gate: price-drift)
try:
    from utils.binance_client import futures_mark_price as _mark_px   # type: ignore
except Exception:
    _mark_px = None  # type: ignore

try:
    from utils.binance_client import futures_index_price as _index_px  # type: ignore
except Exception:
    _index_px = None  # type: ignore

ALPHA_TICK_EWMA = float(os.getenv("EXEC_TICK_EWMA_ALPHA", "0.2"))
ALPHA_WS_LAT_EWMA = float(os.getenv("WS_LAT_EWMA_ALPHA", "0.2"))

# Alerts & Ops thresholds (toggle-able)
OPS_TTL_ALERT_ENABLE     = os.getenv("OPS_TTL_ALERT_ENABLE", "0").lower() in ("1","true","yes","on")
STATUS_PRICE_TTL_ALERT_SEC = float(os.getenv("STATUS_PRICE_TTL_ALERT_SEC", "45"))

OPS_TIMEOUT_ALERT_ENABLE = os.getenv("OPS_TIMEOUT_ALERT_ENABLE", "0").lower() in ("1","true","yes","on")
EXEC_TIMEOUT_BURST_ALERT = int(os.getenv("EXEC_TIMEOUT_BURST_ALERT", "3"))  # timeouts in last 60s

OPS_PRICE_DRIFT_ALERT_ENABLE = os.getenv("OPS_PRICE_DRIFT_ALERT_ENABLE", "0").lower() in ("1","true","yes","on")
OPS_PRICE_DRIFT_BPS     = float(os.getenv("OPS_PRICE_DRIFT_BPS", "25.0"))   # mark vs index

WS_DEGRADE_AUTO         = os.getenv("WS_DEGRADE_AUTO", "1").lower() in ("1","true","yes","on")
WS_DEGRADE_TTL_SEC      = float(os.getenv("WS_DEGRADE_TTL_SEC", "30"))
WS_DEGRADE_RECONNECTS_60S = int(os.getenv("WS_DEGRADE_RECONNECTS_60S", "3"))

# Health universe for drift/ops checks
HEALTH_SYMBOLS = [s.strip().upper() for s in os.getenv("HEALTH_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]

_lock = threading.RLock()

_state: Dict[str, Any] = {
    "executor": {
        "tick_ewma_ms": 0.0,
        "tick_last_dt_ms": 0.0,
        "tick_window_ms": deque(maxlen=600),  # ~10min אם טיק/שנייה
        "p95_ms": 0.0,
        "p99_ms": 0.0,
        "no_trade_streak": 0,
        "interval": None,
        "last_tick_ts": 0.0,
        "timeouts_60s": 0,
        "_timeouts_ts": deque(),  # timestamps
    },
    "orders": {  # אופציונלי: לקשור לעלות סליפג'/latency
        "lat_ms_window": deque(maxlen=2000),
        "p95_ms": 0.0,
        "p99_ms": 0.0,
    },
    "ws_user": {
        "latency_ewma_ms": 0.0,
        "reconnects": 0,
        "_reco_ts": deque(),  # timestamps for last 60s
        "last_event_ts": 0.0,
        "ttl_sec": None,
        "degrade_active": False,
    },
    "price_feed": {
        "last_update_ts": 0.0,
        "ttl_sec": None,
    },
    "ops": {
        "last_ttl_alert_ts": 0.0,
        "last_timeout_burst_ts": 0.0,
        "last_price_drift_alert_ts": 0.0,
        "gate_bump_active": False,
    },
}

def _percentile_fast(data: List[float], q: float) -> float:
    if not data:
        return 0.0
    arr = sorted(data)
    k = (len(arr) - 1) * q
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(arr[int(k)])
    d0 = arr[f] * (c - k)
    d1 = arr[c] * (k - f)
    return float(d0 + d1)

def _update_pxx_from_window(window: deque, where: Dict[str, Any]) -> None:
    arr = list(window)
    where["p95_ms"] = _percentile_fast(arr, 0.95)
    where["p99_ms"] = _percentile_fast(arr, 0.99)

# ===== Public API (called by other modules) =====

def exec_on_batch_timeout() -> None:
    now = time.time()
    with _lock:
        _state["executor"]["_timeouts_ts"].append(now)

def exec_on_trade_sent(symbol: str) -> None:
    # hook – אפשר להרחיב בעתיד (count per symbol, success ratio וכו')
    return

def exec_on_tick_stop(dt_ms: float, current_interval: Optional[int], no_trade_streak: int) -> None:
    now = time.time()
    with _lock:
        s = _state["executor"]
        s["last_tick_ts"] = now
        s["tick_last_dt_ms"] = float(dt_ms)
        ewma = s["tick_ewma_ms"]
        s["tick_ewma_ms"] = (ALPHA_TICK_EWMA * dt_ms) + (1.0 - ALPHA_TICK_EWMA) * (ewma if ewma else dt_ms)
        s["no_trade_streak"] = int(no_trade_streak)
        s["interval"] = current_interval
        s["tick_window_ms"].append(float(dt_ms))
        # cleanup timeouts window (60s)
        tts = s["_timeouts_ts"]
        while tts and now - tts[0] > 60.0:
            tts.popleft()
        s["timeouts_60s"] = len(tts)
        _update_pxx_from_window(s["tick_window_ms"], s)

def record_order_latency_ms(lat_ms: float) -> None:
    with _lock:
        w = _state["orders"]["lat_ms_window"]
        w.append(float(lat_ms))
        _update_pxx_from_window(w, _state["orders"])

def ws_on_event(latency_ms: Optional[float] = None) -> None:
    now = time.time()
    with _lock:
        ws = _state["ws_user"]
        if latency_ms is not None:
            ew = ws["latency_ewma_ms"]
            ws["latency_ewma_ms"] = (ALPHA_WS_LAT_EWMA * float(latency_ms)) + (1.0 - ALPHA_WS_LAT_EWMA) * (ew if ew else float(latency_ms))
        ws["last_event_ts"] = now
        ws["ttl_sec"] = 0.0

def ws_on_reconnect() -> None:
    now = time.time()
    with _lock:
        ws = _state["ws_user"]
        ws["reconnects"] += 1
        ws["_reco_ts"].append(now)

def price_feed_touch() -> None:
    now = time.time()
    with _lock:
        pf = _state["price_feed"]
        pf["last_update_ts"] = now
        pf["ttl_sec"] = 0.0

def _recalc_ttls() -> None:
    now = time.time()
    ws = _state["ws_user"]
    pf = _state["price_feed"]
    ws["ttl_sec"] = (now - ws["last_event_ts"]) if ws["last_event_ts"] else None
    pf["ttl_sec"] = (now - pf["last_update_ts"]) if pf["last_update_ts"] else None

    # clean reconnects window (60s)
    rt = ws["_reco_ts"]
    while rt and now - rt[0] > 60.0:
        rt.popleft()

def ops_tick_safe() -> None:
    """Lightweight ops checks – safe to call each tick."""
    try:
        _recalc_ttls()
        now = time.time()
        ws   = _state["ws_user"]
        ex   = _state["executor"]
        ops  = _state["ops"]

        # ====== Degrade Mode (auto) ======
        if WS_DEGRADE_AUTO:
            degrade_reason = False
            ttl_ok = (ws["ttl_sec"] or 0.0) > WS_DEGRADE_TTL_SEC if ws["ttl_sec"] is not None else False
            many_recents = len(ws["_reco_ts"]) >= WS_DEGRADE_RECONNECTS_60S
            degrade_reason = ttl_ok or many_recents
            ws["degrade_active"] = bool(degrade_reason)

        # ====== TTL Alert (optional) ======
        if OPS_TTL_ALERT_ENABLE and ws["ttl_sec"] is not None and ws["ttl_sec"] > STATUS_PRICE_TTL_ALERT_SEC:
            if now - ops["last_ttl_alert_ts"] > 30.0:  # rate-limit
                ops["last_ttl_alert_ts"] = now
                try:
                    # fire-and-forget
                    import asyncio; asyncio.create_task(_notify_err(f"⚠️ TTL high: {ws['ttl_sec']:.1f}s (WS user)"))
                except Exception:
                    pass

        # ====== Timeout Burst Alert (optional) ======
        if OPS_TIMEOUT_ALERT_ENABLE and ex["timeouts_60s"] >= EXEC_TIMEOUT_BURST_ALERT:
            if now - ops["last_timeout_burst_ts"] > 30.0:
                ops["last_timeout_burst_ts"] = now
                try:
                    import asyncio; asyncio.create_task(_notify_err(f"⚠️ Timeout burst: {ex['timeouts_60s']} in 60s"))
                except Exception:
                    pass

        # ====== Price-Drift Gate-Bump (optional, only if index func exists) ======
        if OPS_PRICE_DRIFT_ALERT_ENABLE and _mark_px and _index_px:
            drift_hit = False
            for sym in HEALTH_SYMBOLS[:5]:  # לא להעמיס
                try:
                    m = float(_mark_px(sym) or 0.0)
                    ix = float(_index_px(sym) or 0.0)
                except Exception:
                    continue
                if m <= 0 or ix <= 0:
                    continue
                bps = abs(m - ix) / ix * 1e4
                if bps >= OPS_PRICE_DRIFT_BPS:
                    drift_hit = True
                    break
            if drift_hit and (now - ops["last_price_drift_alert_ts"] > 60.0):
                ops["last_price_drift_alert_ts"] = now
                ops["gate_bump_active"] = True
                try:
                    import asyncio; asyncio.create_task(_notify_err(f"🚧 Price-Drift detected (>{OPS_PRICE_DRIFT_BPS} bps). Bump gates / prefer Mark-only."))
                except Exception:
                    pass
        else:
            ops["gate_bump_active"] = False

    except Exception:
        # never throw
        return

# ===== Snapshots for REST =====

def get_executor_status() -> Dict[str, Any]:
    with _lock:
        s = _state["executor"]
        o = _state["orders"]
        return {
            "tick_ewma_ms": s["tick_ewma_ms"],
            "tick_last_dt_ms": s["tick_last_dt_ms"],
            "p95_ms": s["p95_ms"],
            "p99_ms": s["p99_ms"],
            "no_trade_streak": s["no_trade_streak"],
            "interval": s["interval"],
            "last_tick_ts": s["last_tick_ts"],
            "timeouts_60s": s["timeouts_60s"],
            "order_p95_ms": o["p95_ms"],
            "order_p99_ms": o["p99_ms"],
            "ops_gate_bump": _state["ops"]["gate_bump_active"],
        }

def get_ws_user_status() -> Dict[str, Any]:
    with _lock:
        ws = _state["ws_user"]
        pf = _state["price_feed"]
        return {
            "latency_ewma_ms": ws["latency_ewma_ms"],
            "reconnects_total": ws["reconnects"],
            "reconnects_60s": len(ws["_reco_ts"]),
            "last_event_ts": ws["last_event_ts"],
            "ttl_sec": ws["ttl_sec"],
            "degrade_active": ws["degrade_active"],
            "price_feed_ttl_sec": pf["ttl_sec"],
            "price_feed_last_ts": pf["last_update_ts"],
        }


