# utils/runtime_counters.py
from __future__ import annotations
import os, time, math, logging, threading
from collections import deque, defaultdict
from typing import Dict, Any, Optional, List

logger = logging.getLogger("algogpt.runtime")

# ------------- helpers / env -------------
def _now() -> float:
    return time.time()

def _getenv_bool(name: str, default: bool) -> bool:
    v = os.getenv(name, str(int(default))).strip().lower()
    return v in ("1", "true", "yes", "on")

def _getenv_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default

def _getenv_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except Exception:
        return default

# ------------- config (read dynamically where needed) -------------
def _cfg() -> Dict[str, Any]:
    return {
        "METRICS_WINDOW_SIZE": _getenv_int("METRICS_WINDOW_SIZE", 2000),
        "WS_LAT_EWMA_ALPHA": _getenv_float("WS_LAT_EWMA_ALPHA", 0.2),
        "EXEC_TICK_EWMA_ALPHA": _getenv_float("EXEC_TICK_EWMA_ALPHA", 0.2),
        "STATUS_PRICE_TTL_ALERT_SEC": _getenv_int("STATUS_PRICE_TTL_ALERT_SEC", 10),
        "EXEC_TIMEOUT_BURST_ALERT": _getenv_int("EXEC_TIMEOUT_BURST_ALERT", 3),
        "OPS_TICK_ENABLE": _getenv_bool("OPS_TICK_ENABLE", True),
        "PRICE_DRIFT_BPS_ALERT": _getenv_float("PRICE_DRIFT_BPS_ALERT", 25.0),

        # Telegram ops
        "OPS_TTL_ALERT_TELEGRAM": _getenv_bool("OPS_TTL_ALERT_TELEGRAM", True),
        "OPS_TIMEOUT_BURST_TELEGRAM": _getenv_bool("OPS_TIMEOUT_BURST_TELEGRAM", True),
        "OPS_DRIFT_ALERT_TELEGRAM": _getenv_bool("OPS_DRIFT_ALERT_TELEGRAM", True),
        "OPS_ALERT_COOLDOWN_SEC": _getenv_int("OPS_ALERT_COOLDOWN_SEC", 120),

        # Degrade & ADX safety
        "OPS_DEGRADE_MAX_LEVERAGE": _getenv_int("OPS_DEGRADE_MAX_LEVERAGE", 12),
        "OPS_ADX_SAFETY_MAX_LEVERAGE": _getenv_int("OPS_ADX_SAFETY_MAX_LEVERAGE", 15),

        # Drift → Degrade
        "OPS_DRIFT_DEGRADE_ENABLE": _getenv_bool("OPS_DRIFT_DEGRADE_ENABLE", True),
        "OPS_DRIFT_DEGRADE_MIN_BPS": _getenv_float("OPS_DRIFT_DEGRADE_MIN_BPS", 30.0),

        # Symbols for drift/health
        "HEALTH_SYMBOLS": [s.strip().upper() for s in os.getenv("HEALTH_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()],
    }

# ------------- telegram -------------
def _tg_send(text: str) -> None:
    bot = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip() or os.getenv("ADMIN_CHAT_ID", "").strip()
    if not bot or not chat:
        return
    try:
        import httpx  # type: ignore
        url = f"https://api.telegram.org/bot{bot}/sendMessage"
        with httpx.Client(timeout=10.0) as cli:
            cli.post(url, data={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"})
    except Exception as e:
        logger.warning("telegram send failed: %s", e)

# ------------- state -------------
_LOCK = threading.RLock()

# WS counters/state
_WS_STATE: Dict[str, Any] = {
    "up": False,
    "up_since_ts": 0.0,
    "last_event_ts": 0.0,
    "last_reconnect_ts": 0.0,
    "reconnects": 0,
    "events_total": 0,
    "events_by_type": defaultdict(int),
    "ewma_latency_ms": None,  # type: Optional[float]
}

# EXEC counters/state
_EXEC_STATE: Dict[str, Any] = {
    "durations_ms": deque(maxlen=_cfg()["METRICS_WINDOW_SIZE"]),
    "ewma_ms": None,  # type: Optional[float]
    "last_tick_ts": 0.0,
    "timeouts_in_row": 0,
    "timeout_bursts": 0,
    "timeout_burst_pending": False,
    "trades_sent_total": 0,
    "last_trade_symbol": "",
    "last_trade_ts": 0.0,
    "current_interval": 0,
    "no_trade_streak": 0,
}

# alerts cooldowns
_ALERT_LAST_TS: Dict[str, float] = {"ttl": 0.0, "timeout_burst": 0.0, "drift": 0.0}

# degrade state
_DEGRADE: Dict[str, Any] = {"active": False, "until_ts": 0.0}

# ------------- small utils -------------
def _ewma(prev: Optional[float], x: float, alpha: float) -> float:
    if prev is None:
        return float(x)
    return float(alpha * x + (1.0 - alpha) * prev)

def _quantiles(values: List[float], qs: List[float]) -> List[float]:
    if not values:
        return [0.0 for _ in qs]
    v = sorted(values)
    n = len(v)
    out = []
    for q in qs:
        if n == 1:
            out.append(v[0]); continue
        pos = (n - 1) * q
        lo = int(math.floor(pos)); hi = int(math.ceil(pos))
        if lo == hi:
            out.append(float(v[lo])); continue
        frac = pos - lo
        out.append(float(v[lo] * (1 - frac) + v[hi] * frac))
    return out

def _cooldown_ok(kind: str, now: float, cooldown: int) -> bool:
    last = _ALERT_LAST_TS.get(kind, 0.0) or 0.0
    return (now - last) >= max(1, cooldown)

def _mark_alert(kind: str, now: float) -> None:
    _ALERT_LAST_TS[kind] = now

def _set_degrade(active: bool, duration_sec: Optional[int] = None) -> None:
    with _LOCK:
        if active:
            _DEGRADE["active"] = True
            t = _now() + float(duration_sec or _cfg()["OPS_ALERT_COOLDOWN_SEC"])
            _DEGRADE["until_ts"] = t
            os.environ["OPS_DEGRADE_ACTIVE"] = "1"
        else:
            _DEGRADE["active"] = False
            _DEGRADE["until_ts"] = 0.0
            os.environ.pop("OPS_DEGRADE_ACTIVE", None)

def is_degrade_active() -> bool:
    with _LOCK:
        if not _DEGRADE["active"]:
            return False
        if _now() >= float(_DEGRADE.get("until_ts", 0.0) or 0.0):
            _set_degrade(False)
            return False
        return True

def get_degrade_state() -> Dict[str, Any]:
    with _LOCK:
        left = max(0.0, float(_DEGRADE.get("until_ts", 0.0) or 0.0) - _now()) if _DEGRADE["active"] else 0.0
        return {"active": bool(_DEGRADE["active"]), "seconds_left": left, "max_leverage": _cfg()["OPS_DEGRADE_MAX_LEVERAGE"]}

# ------------- WS hooks -------------
def ws_note_event(*, latency_ms: Optional[float] = None, etype: Optional[str] = None) -> None:
    cfg = _cfg()
    with _LOCK:
        _WS_STATE["events_total"] += 1
        _WS_STATE["last_event_ts"] = _now()
        if etype:
            _WS_STATE["events_by_type"][str(etype).upper()] += 1
        if latency_ms is not None:
            _WS_STATE["ewma_latency_ms"] = _ewma(_WS_STATE["ewma_latency_ms"], float(latency_ms), cfg["WS_LAT_EWMA_ALPHA"])

def ws_note_reconnect() -> None:
    with _LOCK:
        _WS_STATE["reconnects"] += 1
        _WS_STATE["last_reconnect_ts"] = _now()

def ws_note_up(is_up: bool) -> None:
    with _LOCK:
        if is_up and not _WS_STATE["up"]:
            _WS_STATE["up_since_ts"] = _now()
        _WS_STATE["up"] = bool(is_up)

# ------------- EXEC hooks -------------
def exec_on_batch





