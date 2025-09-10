# utils/runtime_counters.py
from __future__ import annotations
import os, time, math, threading, logging
from collections import deque
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("algogpt.runtime")

# ===== ENV =====
METRICS_WINDOW_SIZE      = int(os.getenv("METRICS_WINDOW_SIZE", "2000"))
WS_LAT_EWMA_ALPHA        = float(os.getenv("WS_LAT_EWMA_ALPHA", "0.2"))
EXEC_TICK_EWMA_ALPHA     = float(os.getenv("EXEC_TICK_EWMA_ALPHA", "0.2"))

TTL_ALERT_SEC            = int(os.getenv("STATUS_PRICE_TTL_ALERT_SEC", "10"))
TIMEOUT_BURST_ALERT      = int(os.getenv("EXEC_TIMEOUT_BURST_ALERT", "3"))
OPS_TICK_ENABLE          = os.getenv("OPS_TICK_ENABLE","1").lower() in ("1","true","on","yes")

DRIFT_BPS_ALERT          = float(os.getenv("PRICE_DRIFT_BPS_ALERT","25"))
DRIFT_DEGRADE_ENABLE     = os.getenv("OPS_DRIFT_DEGRADE_ENABLE","1").lower() in ("1","true","on","yes")
DRIFT_DEGRADE_MIN_BPS    = float(os.getenv("OPS_DRIFT_DEGRADE_MIN_BPS","30"))
DEGRADE_MAX_LEV          = int(os.getenv("OPS_DEGRADE_MAX_LEVERAGE","12"))
ADX_SAFETY_MAX_LEV       = int(os.getenv("OPS_ADX_SAFETY_MAX_LEVERAGE","15"))

OPS_TTL_ALERT_TELEGRAM   = os.getenv("OPS_TTL_ALERT_TELEGRAM","1").lower() in ("1","true","on","yes")
OPS_TIMEOUT_BURST_TELEGRAM = os.getenv("OPS_TIMEOUT_BURST_TELEGRAM","1").lower() in ("1","true","on","yes")
OPS_DRIFT_ALERT_TELEGRAM = os.getenv("OPS_DRIFT_ALERT_TELEGRAM","1").lower() in ("1","true","on","yes")
OPS_ALERT_COOLDOWN_SEC   = int(os.getenv("OPS_ALERT_COOLDOWN_SEC", "120"))

HEALTH_SYMBOLS = [s.strip().upper() for s in os.getenv("HEALTH_SYMBOLS","BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]

# ===== Telegram helper =====
async def _notify_tg(msg: str) -> None:
    try:
        from utils.telegram_notifier import notify_ops_alert
        await notify_ops_alert(msg)  # if exists
        return
    except Exception:
        pass
    try:
        from utils.telegram_notifier import notify_scan_error
        await notify_scan_error(msg)
    except Exception:
        logger.info({"event":"ops.alert", "msg": msg})

_last_alert_ts: Dict[str,float] = {}
def _cooldown_ok(key: str, cool_s: int) -> bool:
    now = time.time()
    ts  = _last_alert_ts.get(key, 0.0)
    if now - ts >= cool_s:
        _last_alert_ts[key] = now
        return True
    return False

# ===== WS counters =====
_ws_lock = threading.Lock()
_ws_up: int = 0
_ws_reconnects: int = 0
_ws_last_event_ts: float = 0.0
_ws_ewma_inter_ms: float = 0.0

def ws_note_up(is_up: bool) -> None:
    global _ws_up
    with _ws_lock:
        _ws_up = 1 if is_up else 0

def ws_note_reconnect() -> None:
    global _ws_reconnects
    with _ws_lock:
        _ws_reconnects += 1

def ws_note_event(*, latency_ms: Optional[float] = None) -> None:
    global _ws_last_event_ts, _ws_ewma_inter_ms
    now = time.time()
    with _ws_lock:
        if _ws_last_event_ts:
            inter_ms = (now - _ws_last_event_ts) * 1000.0
            _ws_ewma_inter_ms = inter_ms if _ws_ewma_inter_ms == 0.0 else (
                (1.0 - WS_LAT_EWMA_ALPHA) * _ws_ewma_inter_ms + WS_LAT_EWMA_ALPHA * inter_ms
            )
        _ws_last_event_ts = now

def ws_get_counters() -> Dict[str, Any]:
    with _ws_lock:
        last_age = round(max(0.0, time.time() - _ws_last_event_ts), 2) if _ws_last_event_ts else None
        return {
            "ws_up": _ws_up,
            "reconnects": _ws_reconnects,
            "ewma_latency_ms": round(_ws_ewma_inter_ms, 2),
            "last_event_age_sec": last_age,
        }

# Compatibility aliases (optional)
def ws_user_status() -> Dict[str, Any]:
    c = ws_get_counters()
    return {
        "running": bool(c["ws_up"]),
        "reconnects": c["reconnects"],
        "ttl_sec": c["last_event_age_sec"],
        "inter_event_ewma_ms": c["ewma_latency_ms"],
    }

# ===== EXEC counters =====
_exec_lock = threading.Lock()
_exec_ewma_dt_ms: float = 0.0
_exec_last_tick_ts: float = 0.0
_exec_dt_hist: deque = deque(maxlen=METRICS_WINDOW_SIZE)
_exec_timeouts: deque = deque(maxlen=512)
_exec_no_trade_streak: int = 0
_exec_current_interval: int = int(os.getenv("SCAN_INTERVAL","60"))

def exec_on_tick_stop(*, dt_ms: float, current_interval: int, no_trade_streak: int) -> None:
    global _exec_last_tick_ts, _exec_ewma_dt_ms, _exec_no_trade_streak, _exec_current_interval
    now = time.time()
    with _exec_lock:
        _exec_last_tick_ts = now
        _exec_dt_hist.append(float(dt_ms))
        _exec_ewma_dt_ms = (1.0 - EXEC_TICK_EWMA_ALPHA) * _exec_ewma_dt_ms + EXEC_TICK_EWMA_ALPHA * float(dt_ms)
        _exec_no_trade_streak = int(no_trade_streak)
        _exec_current_interval = int(current_interval)

def exec_on_batch_timeout() -> None:
    with _exec_lock:
        _exec_timeouts.append(time.time())

def exec_on_trade_sent(symbol: str) -> None:
    return None

def _percentile(d: deque, p: float) -> Optional[float]:
    if not d:
        return None
    arr = sorted(d)
    if len(arr) == 1:
        return float(arr[0])
    k = (len(arr)-1) * (float(p)/100.0)
    f = math.floor(k); c = math.ceil(k)
    if f == c: 
        return float(arr[int(k)])
    return float(arr[f] + (k - f) * (arr[c] - arr[f]))

def exec_get_counters() -> Dict[str, Any]:
    with _exec_lock:
        p95 = _percentile(_exec_dt_hist, 95.0)
        p99 = _percentile(_exec_dt_hist, 99.0)
        last_age = round(max(0.0, time.time() - _exec_last_tick_ts), 2) if _exec_last_tick_ts else None
        timeouts_60s = sum(1 for t in _exec_timeouts if t >= time.time() - 60)
        return {
            "tick_ewma_ms": round(_exec_ewma_dt_ms, 2),
            "tick_p95_ms": round(p95, 2) if p95 is not None else None,
            "tick_p99_ms": round(p99, 2) if p99 is not None else None,
            "last_tick_age_sec": last_age,
            "timeouts_burst": int(timeouts_60s),
            "no_trade_streak": _exec_no_trade_streak,
            "current_interval": _exec_current_interval,
        }

# Compatibility alias
def executor_status() -> Dict[str, Any]:
    return exec_get_counters()

# ===== Price drift storage (for leverage_policy) =====
_PRICE_DRIFT_LAST_BPS: float = 0.0
_PRICE_DRIFT_LAST_TS: float = 0.0

def price_set_last_drift_bps(bps: float) -> None:
    global _PRICE_DRIFT_LAST_BPS, _PRICE_DRIFT_LAST_TS
    _PRICE_DRIFT_LAST_BPS = float(bps)
    _PRICE_DRIFT_LAST_TS = time.time()

def price_get_last_drift_bps(max_age_sec: int = 60) -> float:
    if _PRICE_DRIFT_LAST_TS == 0.0:
        return 0.0
    age = time.time() - _PRICE_DRIFT_LAST_TS
    return _PRICE_DRIFT_LAST_BPS if age <= max_age_sec else 0.0

# ===== Internal helpers for alerts =====
def _get_ws_price_ttl_sec() -> float:
    # אם יש מודול ws_fallback עם חותמות זמן פר סימבול — העדף אותו
    try:
        from utils import ws_fallback
        now = time.time()
        ttls: List[float] = []
        for sym in HEALTH_SYMBOLS:
            try:
                ts = float(ws_fallback.get_last_ts(sym))
                if ts > 0:
                    ttls.append(max(0.0, now - ts))
            except Exception:
                pass
        if ttls:
            return max(ttls)
    except Exception:
        pass
    # אחרת TTL כללי של אירוע WS אחרון
    return max(0.0, time.time() - _ws_last_event_ts) if _ws_last_event_ts else 1e9

def _index_price(symbol: str) -> Optional[float]:
    try:
        from utils.binance_client import futures_index_price
        p = futures_index_price(symbol)
        if p and p > 0:
            return float(p)
    except Exception:
        return None
    return None

def _mark_price(symbol: str) -> Optional[float]:
    try:
        from utils.binance_client import futures_mark_price
        p = futures_mark_price(symbol)
        if p and p > 0:
            return float(p)
    except Exception:
        return None
    return None

def _check_price_drift() -> Tuple[float, Optional[str], Optional[float], Optional[float]]:
    max_bps = -1.0
    max_sym: Optional[str] = None
    max_m: Optional[float] = None
    max_i: Optional[float] = None
    for sym in HEALTH_SYMBOLS:
        idx = _index_price(sym)
        mrk = _mark_price(sym)
        if not idx or not mrk or idx <= 0:
            continue
        bps = abs(mrk - idx) / idx * 10000.0
        if bps > max_bps:
            max_bps, max_sym, max_m, max_i = bps, sym, mrk, idx
    return (max_bps if max_bps >= 0 else 0.0, max_sym, max_m, max_i)

# ===== Ops tick (alerts + optional degrade) =====
def ops_tick_safe() -> None:
    if not OPS_TICK_ENABLE:
        return

    # 1) TTL alert
    try:
        ttl = _get_ws_price_ttl_sec()
        if OPS_TTL_ALERT_TELEGRAM and ttl > TTL_ALERT_SEC and _cooldown_ok("ttl", OPS_ALERT_COOLDOWN_SEC):
            import asyncio; asyncio.create_task(_notify_tg(f"⚠️ TTL Alert: price_feed ttl={ttl:.1f}s > {TTL_ALERT_SEC}s"))
    except Exception as e:
        logger.debug({"event":"ops.ttl_check_err", "err": str(e)})

    # 2) Timeout-burst alert
    try:
        with _exec_lock:
            burst = sum(1 for t in _exec_timeouts if t >= time.time() - 60)
        if OPS_TIMEOUT_BURST_TELEGRAM and burst >= TIMEOUT_BURST_ALERT and _cooldown_ok("timeout_burst", OPS_ALERT_COOLDOWN_SEC):
            import asyncio; asyncio.create_task(_notify_tg(f"⏱️ Timeout Burst: last_60s={burst} (≥{TIMEOUT_BURST_ALERT})"))
    except Exception as e:
        logger.debug({"event":"ops.timeout_check_err", "err": str(e)})

    # 3) Price drift alert (+ expose to leverage_policy)
    try:
        max_bps, sym, mrk, idx = _check_price_drift()
        if max_bps > 0:
            price_set_last_drift_bps(max_bps)
        if sym and max_bps >= DRIFT_BPS_ALERT:
            if OPS_DRIFT_ALERT_TELEGRAM and _cooldown_ok("drift", OPS_ALERT_COOLDOWN_SEC):
                import asyncio
                msg = f"📉 Price-Drift: {sym} | drift={max_bps:.1f}bps (mark={mrk or 'NA'} vs index={idx or 'NA'}) | thr={DRIFT_BPS_ALERT:.1f}bps"
                asyncio.create_task(_notify_tg(msg))
            if DRIFT_DEGRADE_ENABLE and max_bps >= max(DRIFT_BPS_ALERT, DRIFT_DEGRADE_MIN_BPS):
                logger.warning({"event":"ops.degrade_suggest", "symbol": sym, "bps": round(max_bps,1), "cap": DEGRADE_MAX_LEV})
    except Exception as e:
        logger.debug({"event":"ops.drift_check_err", "err": str(e)})

__all__ = [
    # WS
    "ws_note_up", "ws_note_reconnect", "ws_note_event", "ws_get_counters", "ws_user_status",
    # EXEC
    "exec_on_tick_stop", "exec_on_batch_timeout", "exec_on_trade_sent", "exec_get_counters", "executor_status",
    # OPS / Alerts
    "ops_tick_safe",
    # Drift store (used by leverage_policy)
    "price_set_last_drift_bps", "price_get_last_drift_bps",
]







