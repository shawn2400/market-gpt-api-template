# utils/runtime_counters.py
from __future__ import annotations
import os, time, math, logging
from collections import deque
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("algogpt.runtime")

# ========= ENV / Defaults =========
# EWMA
WS_LAT_EWMA_ALPHA      = float(os.getenv("WS_LAT_EWMA_ALPHA", "0.2"))
EXEC_TICK_EWMA_ALPHA   = float(os.getenv("EXEC_TICK_EWMA_ALPHA", "0.2"))

# Alerts thresholds
STATUS_PRICE_TTL_ALERT_SEC = int(os.getenv("STATUS_PRICE_TTL_ALERT_SEC", "10"))
EXEC_TIMEOUT_BURST_ALERT   = int(os.getenv("EXEC_TIMEOUT_BURST_ALERT", "3"))
PRICE_DRIFT_BPS_ALERT      = float(os.getenv("PRICE_DRIFT_BPS_ALERT", "25"))

# Telegram alerts (on by default)
OPS_TG_ENABLE              = os.getenv("OPS_TG_ENABLE", "1").lower() in ("1","true","on","yes")
OPS_TG_PRICE_DRIFT_ENABLE  = os.getenv("OPS_TG_PRICE_DRIFT_ENABLE", "1").lower() in ("1","true","on","yes")
OPS_TG_TTL_ENABLE          = os.getenv("OPS_TG_TTL_ENABLE", "1").lower() in ("1","true","on","yes")
OPS_TG_TIMEOUT_ENABLE      = os.getenv("OPS_TG_TIMEOUT_ENABLE", "1").lower() in ("1","true","on","yes")

OPS_ALERT_COOLDOWN_SEC     = int(os.getenv("OPS_ALERT_COOLDOWN_SEC", "120"))
TIMEOUT_BURST_WINDOW_SEC   = int(os.getenv("TIMEOUT_BURST_WINDOW_SEC", "180"))

# Degrade / leverage caps
DEGRADE_ENABLE             = os.getenv("DEGRADE_ENABLE", "1").lower() in ("1","true","on","yes")
DEGRADE_MAX_LEVERAGE       = int(os.getenv("DEGRADE_MAX_LEVERAGE", "12"))  # cap בזמן degrade
DEGRADE_DURATION_SEC       = int(os.getenv("DEGRADE_DURATION_SEC", "900")) # 15min
DEGRADE_BUMP_EXTEND_SEC    = int(os.getenv("DEGRADE_BUMP_EXTEND_SEC", "300"))
MAX_LEVERAGE_GLOBAL        = int(os.getenv("MAX_LEVERAGE", "35"))          # לתיעוד/קלמפ כללי
MIN_LEVERAGE_GLOBAL        = int(os.getenv("MIN_LEVERAGE", "5"))

# Health symbols for price drift checks
_HEALTH_SYMBOLS = [s.strip().upper() for s in (os.getenv("HEALTH_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")) if s.strip()]

# Telegram settings (reuse global bot)
_TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_TELEGRAM_CHAT_ID    = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")

# Optional external modules
try:
    # For mark/index prices
    from utils.binance_client import futures_mark_price, futures_index_price
except Exception as e:
    futures_mark_price = None  # type: ignore
    futures_index_price = None # type: ignore
    logger.warning({"event":"runtime.import_missing", "mod":"utils.binance_client", "err": str(e)})

try:
    # WS status (optional)
    from utils import ws_user_stream
    _have_ws_stream = True
except Exception:
    _have_ws_stream = False

# ========== Telegram ==========
def _tg_send(text: str) -> None:
    if not OPS_TG_ENABLE or not _TELEGRAM_BOT_TOKEN or not _TELEGRAM_CHAT_ID:
        return
    try:
        import httpx  # type: ignore
        api = f"https://api.telegram.org/bot{_TELEGRAM_BOT_TOKEN}/sendMessage"
        with httpx.Client(timeout=10.0) as cli:
            cli.post(api, data={
                "chat_id": _TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            })
    except Exception as e:
        logger.warning({"event":"tg.send_failed", "err": str(e)})

# ========== Helpers ==========
def _ewma(prev: Optional[float], x: float, alpha: float) -> float:
    if prev is None:
        return x
    return (1.0 - alpha) * float(prev) + alpha * float(x)

def _percentile(sorted_list: List[float], p: float) -> float:
    if not sorted_list:
        return 0.0
    n = len(sorted_list)
    if n == 1:
        return float(sorted_list[0])
    rank = (p/100.0) * (n - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(sorted_list[lo])
    w = rank - lo
    return float(sorted_list[lo] * (1.0 - w) + sorted_list[hi] * w)

def _now() -> float:
    return time.time()

# ========== WS counters ==========
_ws_last_event_ts: Optional[float] = None
_ws_event_lat_ewma_ms: Optional[float] = None
_ws_reconnects: int = 0
_ws_up: bool = False

def ws_note_event(*, latency_ms: Optional[float]) -> None:
    """Call from ws_user_stream on each message (OPTIONAL)."""
    global _ws_last_event_ts, _ws_event_lat_ewma_ms
    _ws_last_event_ts = _now()
    if latency_ms is not None:
        _ws_event_lat_ewma_ms = _ewma(_ws_event_lat_ewma_ms, float(latency_ms), WS_LAT_EWMA_ALPHA)

def ws_note_reconnect() -> None:
    global _ws_reconnects
    _ws_reconnects += 1

def ws_note_up(is_up: bool) -> None:
    global _ws_up
    _ws_up = bool(is_up)

# ========== Executor counters ==========
_exec_tick_ewma_ms: Optional[float] = None
_exec_tick_samples_ms: deque = deque(maxlen=400)
_exec_timeouts_ts: deque = deque(maxlen=200)   # batch-timeout events timestamps
_exec_trades_sent: int = 0
_exec_last_interval_s: int = 0
_exec_no_trade_streak: int = 0
_exec_last_tick_ts: Optional[float] = None

def exec_on_trade_sent(symbol: str) -> None:
    global _exec_trades_sent
    _exec_trades_sent += 1

def exec_on_batch_timeout() -> None:
    _exec_timeouts_ts.append(_now())

def exec_on_tick_stop(*, dt_ms: float, current_interval: int, no_trade_streak: int) -> None:
    global _exec_tick_ewma_ms, _exec_last_interval_s, _exec_no_trade_streak, _exec_last_tick_ts
    _exec_tick_ewma_ms = _ewma(_exec_tick_ewma_ms, float(dt_ms), EXEC_TICK_EWMA_ALPHA)
    _exec_tick_samples_ms.append(float(dt_ms))
    _exec_last_interval_s = int(current_interval)
    _exec_no_trade_streak = int(no_trade_streak)
    _exec_last_tick_ts = _now()

# ========== Degrade / ops-gate ==========
_degrade_until_ts: float = 0.0
_degrade_reason: str = ""
_degrade_bumps: int = 0

def degrade_active() -> bool:
    return _now() < _degrade_until_ts

def leverage_cap() -> int:
    """Current leverage cap if degrade is active, else global MAX."""
    if degrade_active():
        return int(max(1, DEGRADE_MAX_LEVERAGE))
    return int(MAX_LEVERAGE_GLOBAL)

def clamp_leverage(leverage: int) -> int:
    return int(max(MIN_LEVERAGE_GLOBAL, min(leverage_cap(), int(leverage))))

def degrade_activate(reason: str, *, duration_sec: Optional[int] = None) -> None:
    global _degrade_until_ts, _degrade_reason, _degrade_bumps
    dur = int(duration_sec or DEGRADE_DURATION_SEC)
    now = _now()
    if now < _degrade_until_ts:
        # extend
        _degrade_until_ts = max(_degrade_until_ts, now + min(max(60, DEGRADE_BUMP_EXTEND_SEC), dur))
    else:
        _degrade_until_ts = now + dur
    _degrade_reason = reason
    _degrade_bumps += 1
    logger.warning({"event":"ops.degrade_activated", "reason": reason, "until": _degrade_until_ts, "cap": leverage_cap()})

def degrade_clear() -> None:
    global _degrade_until_ts, _degrade_reason
    _degrade_until_ts = 0.0
    _degrade_reason = ""
    logger.info({"event":"ops.degrade_cleared"})

def ops_gate_bump(reason: str) -> None:
    """Public hook to tighten leverage dynamically."""
    if not DEGRADE_ENABLE:
        return
    degrade_activate(reason=reason)

# ========== Status getters for routers ==========
def ws_user_status() -> Dict[str, Any]:
    last_age = None
    if _ws_last_event_ts:
        last_age = max(0.0, _now() - _ws_last_event_ts)
    return {
        "ws_up": int(_ws_up),
        "last_event_age_sec": last_age,
        "event_latency_ewma_ms": _ws_event_lat_ewma_ms,
        "reconnects": _ws_reconnects,
    }

def _sorted_samples() -> List[float]:
    return sorted(list(_exec_tick_samples_ms)) if _exec_tick_samples_ms else []

def executor_status() -> Dict[str, Any]:
    s = _sorted_samples()
    p95 = _percentile(s, 95.0) if s else 0.0
    p99 = _percentile(s, 99.0) if s else 0.0
    timeouts_recent = _timeouts_in_window(TIMEOUT_BURST_WINDOW_SEC)
    return {
        "tick_ewma_ms": _exec_tick_ewma_ms,
        "tick_p95_ms": p95,
        "tick_p99_ms": p99,
        "timeouts_total": len(_exec_timeouts_ts),
        "timeouts_recent_window_sec": TIMEOUT_BURST_WINDOW_SEC,
        "timeouts_recent_count": timeouts_recent,
        "trades_sent_total": _exec_trades_sent,
        "last_interval_sec": _exec_last_interval_s,
        "no_trade_streak": _exec_no_trade_streak,
        "degrade_active": degrade_active(),
        "leverage_cap": leverage_cap(),
        "degrade_reason": _degrade_reason,
        "degrade_bumps": _degrade_bumps,
    }

# ========== Alert logic ==========
_last_tg_ttl_alert_ts: float = 0.0
_last_tg_timeout_alert_ts: float = 0.0
_symbol_last_drift_alert_ts: Dict[str, float] = {}

def _cooldown_ok(last_ts: float) -> bool:
    return (_now() - last_ts) >= OPS_ALERT_COOLDOWN_SEC

def _timeouts_in_window(window_sec: int) -> int:
    cutoff = _now() - window_sec
    while _exec_timeouts_ts and _exec_timeouts_ts[0] < cutoff:
        _exec_timeouts_ts.popleft()
    return len(_exec_timeouts_ts)

def _check_ttl_alert() -> None:
    """Alert when no WS events received for too long."""
    global _last_tg_ttl_alert_ts
    if not OPS_TG_TTL_ENABLE:
        return
    if _ws_last_event_ts is None:
        return
    age = _now() - _ws_last_event_ts
    if age >= STATUS_PRICE_TTL_ALERT_SEC and _cooldown_ok(_last_tg_ttl_alert_ts):
        _tg_send(f"⚠️ <b>WS TTL Alert</b> — לא התקבלו אירועים {int(age)}s (thr={STATUS_PRICE_TTL_ALERT_SEC}s).")
        _last_tg_ttl_alert_ts = _now()
        ops_gate_bump("ttl_alert")

def _check_timeout_burst_alert() -> None:
    """Alert on a burst of batch timeouts within a time window."""
    global _last_tg_timeout_alert_ts
    if not OPS_TG_TIMEOUT_ENABLE:
        return
    recent = _timeouts_in_window(TIMEOUT_BURST_WINDOW_SEC)
    if recent >= max(1, EXEC_TIMEOUT_BURST_ALERT) and _cooldown_ok(_last_tg_timeout_alert_ts):
        _tg_send(f"⛔ <b>Timeout Burst</b> — {recent} timeouts ב-{TIMEOUT_BURST_WINDOW_SEC}s (thr={EXEC_TIMEOUT_BURST_ALERT}).")
        _last_tg_timeout_alert_ts = _now()
        ops_gate_bump("timeout_burst")

def _bps(a: float, b: float) -> float:
    if b <= 0: 
        return 0.0
    return abs(a - b) / b * 10000.0

def _check_price_drift_alert() -> None:
    """Compare mark vs index price for a small health set; alert + degrade on breach."""
    if not OPS_TG_PRICE_DRIFT_ENABLE:
        return
    if futures_mark_price is None or futures_index_price is None:
        return
    now = _now()
    for sym in _HEALTH_SYMBOLS:
        try:
            mark = futures_mark_price(sym)
            index = futures_index_price(sym)
            if mark is None or index is None or index <= 0:
                continue
            drift = _bps(float(mark), float(index))
            if drift >= PRICE_DRIFT_BPS_ALERT:
                last = _symbol_last_drift_alert_ts.get(sym, 0.0)
                if (now - last) >= OPS_ALERT_COOLDOWN_SEC:
                    _tg_send(f"📈 <b>Price-Drift Alert</b> {sym}: drift={drift:.1f} bps (thr={PRICE_DRIFT_BPS_ALERT}).\n"
                             f"mark={mark:.6f} • index={index:.6f}")
                    _symbol_last_drift_alert_ts[sym] = now
                    ops_gate_bump(f"price_drift:{sym}")
        except Exception as e:
            logger.debug({"event":"drift.check_failed", "symbol": sym, "err": str(e)})

# ========== Public tick (call each loop) ==========
def ops_tick_safe() -> None:
    """
    Lightweight periodic ops check:
      - TTL alert (WS inactivity)
      - Timeout burst alert
      - Price drift alert (mark vs index)
      - Activates degrade() when relevant
    """
    try:
        _check_ttl_alert()
    except Exception as e:
        logger.debug({"event":"ops.ttl_alert_fail", "err": str(e)})

    try:
        _check_timeout_burst_alert()
    except Exception as e:
        logger.debug({"event":"ops.timeout_alert_fail", "err": str(e)})

    try:
        _check_price_drift_alert()
    except Exception as e:
        logger.debug({"event":"ops.drift_alert_fail", "err": str(e)})

# ========== Debug dump ==========
def ops_debug_state() -> Dict[str, Any]:
    return {
        "ws": ws_user_status(),
        "exec": executor_status(),
        "config": {
            "TTL_thr_sec": STATUS_PRICE_TTL_ALERT_SEC,
            "timeout_burst_thr": EXEC_TIMEOUT_BURST_ALERT,
            "timeout_window_sec": TIMEOUT_BURST_WINDOW_SEC,
            "price_drift_bps_thr": PRICE_DRIFT_BPS_ALERT,
            "ops_alert_cooldown_sec": OPS_ALERT_COOLDOWN_SEC,
            "degrade_enable": DEGRADE_ENABLE,
            "degrade_max_leverage": DEGRADE_MAX_LEVERAGE,
            "degrade_duration_sec": DEGRADE_DURATION_SEC,
        },
    }

__all__ = [
    # WS hooks
    "ws_note_event", "ws_note_reconnect", "ws_note_up",
    # Executor hooks
    "exec_on_trade_sent", "exec_on_batch_timeout", "exec_on_tick_stop",
    # Status
    "ws_user_status", "executor_status", "ops_debug_state",
    # Ops tick
    "ops_tick_safe",
    # Degrade / leverage
    "ops_gate_bump", "degrade_active", "degrade_clear",
    "leverage_cap", "clamp_leverage",
]





