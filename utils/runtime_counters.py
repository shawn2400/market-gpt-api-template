# utils/runtime_counters.py
from __future__ import annotations
import os, time, math, logging, statistics
from typing import Optional, Dict, Any, List
from collections import deque, defaultdict

logger = logging.getLogger("algogpt.runtime")

# ===== ENV =====
METRICS_WINDOW_SIZE = int(os.getenv("METRICS_WINDOW_SIZE", "2000"))
WS_LAT_EWMA_ALPHA = float(os.getenv("WS_LAT_EWMA_ALPHA", "0.2"))
EXEC_TICK_EWMA_ALPHA = float(os.getenv("EXEC_TICK_EWMA_ALPHA", "0.2"))
STATUS_PRICE_TTL_ALERT_SEC = int(os.getenv("STATUS_PRICE_TTL_ALERT_SEC", "10"))
EXEC_TIMEOUT_BURST_ALERT = int(os.getenv("EXEC_TIMEOUT_BURST_ALERT", "3"))
OPS_TICK_ENABLE = os.getenv("OPS_TICK_ENABLE", "1").lower() in ("1", "true", "yes", "on")

PRICE_DRIFT_BPS_ALERT = float(os.getenv("PRICE_DRIFT_BPS_ALERT", "25"))

# Ops alerts (Telegram) flags/cooldown
OPS_TTL_ALERT_TELEGRAM = os.getenv("OPS_TTL_ALERT_TELEGRAM", "1").lower() in ("1","true","yes","on")
OPS_TIMEOUT_BURST_TELEGRAM = os.getenv("OPS_TIMEOUT_BURST_TELEGRAM", "1").lower() in ("1","true","yes","on")
OPS_DRIFT_ALERT_TELEGRAM = os.getenv("OPS_DRIFT_ALERT_TELEGRAM", "1").lower() in ("1","true","yes","on")
OPS_ALERT_COOLDOWN_SEC = int(os.getenv("OPS_ALERT_COOLDOWN_SEC", "120"))

# Degrade / leverage protection
OPS_DEGRADE_MAX_LEVERAGE = int(os.getenv("OPS_DEGRADE_MAX_LEVERAGE", "12"))
OPS_ADX_SAFETY_MAX_LEVERAGE = int(os.getenv("OPS_ADX_SAFETY_MAX_LEVERAGE", "15"))
OPS_ADX_LEVERAGE_CUTOFFS = [int(x) for x in os.getenv("OPS_ADX_LEVERAGE_CUTOFFS", "20,25,30").split(",") if x.strip().isdigit()]

OPS_DRIFT_DEGRADE_ENABLE = os.getenv("OPS_DRIFT_DEGRADE_ENABLE", "1").lower() in ("1","true","yes","on")
OPS_DRIFT_DEGRADE_MIN_BPS = float(os.getenv("OPS_DRIFT_DEGRADE_MIN_BPS", "30"))

# Health symbols to check drift on
HEALTH_SYMBOLS = [s.strip().upper() for s in os.getenv("HEALTH_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]

# (Optional) Opp boost knobs (only suggested in counters; not enforcing)
OPP_BOOST_ENABLE = os.getenv("OPP_BOOST_ENABLE", "1").lower() in ("1","true","yes","on")
OPP_BATCH_VIABLE_THRESHOLD = int(os.getenv("OPP_BATCH_VIABLE_THRESHOLD", "3"))
OPP_CONC_BOOST_FACTOR = float(os.getenv("OPP_CONC_BOOST_FACTOR", "1.5"))
OPP_MAX_CONC = int(os.getenv("OPP_MAX_CONC", "8"))
OPP_COOLDOWN_SEC = int(os.getenv("OPP_COOLDOWN_SEC", "90"))
OPP_DECAY_FACTOR = float(os.getenv("OPP_DECAY_FACTOR", "0.8"))

# Telegram creds (direct API)
_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))

# ===== Internal state =====
_now = lambda: time.time()
_now_ms = lambda: int(time.time() * 1000)

_ws: Dict[str, Any] = {
    "up": False,
    "events_total": 0,
    "reconnects": 0,
    "last_event_ms": None,
    "last_latency_ms": None,
    "ewma_latency_ms": None,
    "lat_hist": deque(maxlen=METRICS_WINDOW_SIZE),
    "last_up_change_ms": None,
}

_exec: Dict[str, Any] = {
    "last_tick_ms": None,
    "ewma_ms": None,
    "p_hist": deque(maxlen=METRICS_WINDOW_SIZE),
    "timeouts_total": 0,
    "timeouts_since_tick": 0,
    "trades_sent_total": 0,
    "trades_sent_this_tick": 0,
    "last_timeout_ts": None,
    "current_interval": None,
    "no_trade_streak": 0,
    "suggested_conc": None,
    "boost_until": 0.0,
    "boost_active": False,
}

_alert_last_sent: Dict[str, float] = defaultdict(lambda: 0.0)

_drift_snapshot: Dict[str, Any] = {
    "symbols": {},
    "last_check_ts": 0.0,
    "last_alert_ts": 0.0,
    "max_bps": 0.0,
}

_degrade: Dict[str, Any] = {
    "active": False,
    "cap": None,  # int | None
    "reason": "",
    "until": 0.0,
}

# ===== Helpers =====
def _percentile(arr: List[float], q: float) -> Optional[float]:
    if not arr:
        return None
    arr_sorted = sorted(arr)
    k = (len(arr_sorted)-1) * (q/100.0)
    f = math.floor(k); c = math.ceil(k)
    if f == c:
        return float(arr_sorted[int(k)])
    d0 = arr_sorted[int(f)] * (c-k)
    d1 = arr_sorted[int(c)] * (k-f)
    return float(d0+d1)

def _ewma(prev: Optional[float], x: float, alpha: float) -> float:
    return x if prev is None else (alpha * x + (1.0 - alpha) * prev)

def _cooldown_ok(key: str, now: float, cooldown: int = OPS_ALERT_COOLDOWN_SEC) -> bool:
    last = _alert_last_sent.get(key, 0.0)
    if (now - last) >= cooldown:
        _alert_last_sent[key] = now
        return True
    return False

def _tg_send(text: str) -> None:
    if not (_BOT_TOKEN and _CHAT_ID):
        return
    try:
        import httpx  # type: ignore
        base = f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage"
        with httpx.Client(timeout=10.0) as cli:
            cli.post(base, data={
                "chat_id": str(_CHAT_ID),
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            })
    except Exception as e:
        logger.warning("telegram send failed: %s", e)

def _fmt_ms(ms: Optional[float]) -> str:
    if ms is None:
        return "-"
    return f"{ms:.0f}ms"

def _fmt_age_sec(ts_ms: Optional[int]) -> str:
    if not ts_ms:
        return "-"
    age = max(0.0, (_now_ms() - int(ts_ms)) / 1000.0)
    return f"{age:.1f}s"

# ===== WS API =====
def ws_note_event(*, latency_ms: Optional[float] = None) -> None:
    _ws["events_total"] += 1
    _ws["last_event_ms"] = _now_ms()
    if latency_ms is not None:
        _ws["last_latency_ms"] = float(latency_ms)
        _ws["ewma_latency_ms"] = _ewma(_ws["ewma_latency_ms"], float(latency_ms), WS_LAT_EWMA_ALPHA)
        try:
            _ws["lat_hist"].append(float(latency_ms))
        except Exception:
            pass

def ws_note_reconnect() -> None:
    _ws["reconnects"] += 1

def ws_note_up(is_up: bool) -> None:
    if bool(_ws["up"]) != bool(is_up):
        _ws["up"] = bool(is_up)
        _ws["last_up_change_ms"] = _now_ms()

def ws_get_counters() -> Dict[str, Any]:
    last_event_ms = _ws.get("last_event_ms")
    age_sec = None
    if last_event_ms:
        age_sec = max(0.0, (_now_ms() - int(last_event_ms)) / 1000.0)
    lat_hist = list(_ws["lat_hist"])
    p95 = _percentile(lat_hist, 95.0) if lat_hist else None
    p99 = _percentile(lat_hist, 99.0) if lat_hist else None
    return {
        "up": bool(_ws["up"]),
        "events_total": int(_ws["events_total"]),
        "reconnects": int(_ws["reconnects"]),
        "last_event_ms": int(last_event_ms) if last_event_ms else None,
        "last_event_age_sec": age_sec,
        "last_latency_ms": _ws.get("last_latency_ms"),
        "ewma_latency_ms": _ws.get("ewma_latency_ms"),
        "p95_latency_ms": p95,
        "p99_latency_ms": p99,
        "last_up_change_ms": _ws.get("last_up_change_ms"),
    }

# ===== EXEC API =====
def exec_on_batch_timeout() -> None:
    _exec["timeouts_total"] += 1
    _exec["timeouts_since_tick"] += 1
    _exec["last_timeout_ts"] = _now()

def exec_on_trade_sent(symbol: str) -> None:
    _exec["trades_sent_total"] += 1
    _exec["trades_sent_this_tick"] += 1

def exec_on_tick_stop(*, dt_ms: float, current_interval: int, no_trade_streak: int) -> None:
    _exec["last_tick_ms"] = _now_ms()
    _exec["ewma_ms"] = _ewma(_exec.get("ewma_ms"), float(dt_ms), EXEC_TICK_EWMA_ALPHA)
    try:
        _exec["p_hist"].append(float(dt_ms))
    except Exception:
        pass
    _exec["current_interval"] = int(current_interval)
    _exec["no_trade_streak"] = int(no_trade_streak)

    # Suggest "opportunity boost" (informational)
    if OPP_BOOST_ENABLE:
        if _exec["trades_sent_this_tick"] >= OPP_BATCH_VIABLE_THRESHOLD:
            _exec["suggested_conc"] = min(OPP_MAX_CONC, int(math.ceil(int(os.getenv("SCAN_CONCURRENCY","4")) * OPP_CONC_BOOST_FACTOR)))
            _exec["boost_until"] = _now() + OPP_COOLDOWN_SEC
            _exec["boost_active"] = True
        elif _exec["boost_active"] and _now() > _exec["boost_until"]:
            _exec["suggested_conc"] = max(1, int((_exec.get("suggested_conc") or int(os.getenv("SCAN_CONCURRENCY","4"))) * OPP_DECAY_FACTOR))
            _exec["boost_active"] = False

    # בדיקות אופס יבוצעו ב-ops_tick_safe()
    # reset per-tick counters (אחרי שתיבדקנה)
    # (נעשה reset בתוך ops_tick_safe כדי שיספור גם לאלרט)

def exec_get_counters() -> Dict[str, Any]:
    hist = list(_exec["p_hist"])
    p95 = _percentile(hist, 95.0) if hist else None
    p99 = _percentile(hist, 99.0) if hist else None
    ttl_age = None
    if _ws.get("last_event_ms"):
        ttl_age = max(0.0, (_now_ms() - int(_ws["last_event_ms"])) / 1000.0)
    return {
        "last_tick_ms": _exec.get("last_tick_ms"),
        "ewma_tick_ms": _exec.get("ewma_ms"),
        "p95_tick_ms": p95,
        "p99_tick_ms": p99,
        "timeouts_total": int(_exec["timeouts_total"]),
        "timeouts_since_tick": int(_exec["timeouts_since_tick"]),
        "trades_sent_total": int(_exec["trades_sent_total"]),
        "trades_sent_this_tick": int(_exec["trades_sent_this_tick"]),
        "current_interval": int(_exec["current_interval"] or 0),
        "no_trade_streak": int(_exec["no_trade_streak"]),
        "ws_last_event_age_sec": ttl_age,
        "suggested_scan_conc": _exec.get("suggested_conc"),
        "degrade_active": bool(_degrade["active"]),
        "degrade_cap": _degrade.get("cap"),
        "degrade_reason": _degrade.get("reason"),
        "drift_max_bps": _drift_snapshot.get("max_bps"),
        "drift_last_check_ts": _drift_snapshot.get("last_check_ts"),
    }

# ===== Drift / TTL / Burst checks =====
def _check_ttl_and_alert(now: float) -> None:
    if not OPS_TTL_ALERT_TELEGRAM:
        return
    last_ms = _ws.get("last_event_ms")
    if not last_ms:
        return
    age_sec = max(0.0, (_now_ms() - int(last_ms)) / 1000.0)
    if age_sec >= STATUS_PRICE_TTL_ALERT_SEC:
        if _cooldown_ok("ttl", now):
            _tg_send(f"⚠️ <b>TTL Alert</b>: אין אירוע WS {age_sec:.1f}s | EWMA={_fmt_ms(_ws.get('ewma_latency_ms'))} | up={_ws['up']}")

def _check_timeouts_burst_and_alert(now: float) -> None:
    if _exec["timeouts_since_tick"] >= EXEC_TIMEOUT_BURST_ALERT and OPS_TIMEOUT_BURST_TELEGRAM:
        if _cooldown_ok("timeouts", now):
            _tg_send(f"⏱️ <b>Batch Timeout Burst</b>: {int(_exec['timeouts_since_tick'])} בטיק | EWMA tick={_fmt_ms(_exec.get('ewma_ms'))} | interval={_exec.get('current_interval')}s")

def _compute_drift_for_symbol(symbol: str) -> Optional[float]:
    try:
        from utils.binance_client import futures_mark_price, futures_index_price
        m = futures_mark_price(symbol) or 0.0
        i = futures_index_price(symbol) or 0.0
        if m <= 0 or i <= 0:
            return None
        bps = abs((float(m) - float(i)) / float(i)) * 10000.0
        return float(bps)
    except Exception as e:
        logger.debug("drift compute failed for %s: %s", symbol, e)
        return None

def _check_drift_and_maybe_alert(now: float) -> None:
    max_bps = 0.0
    details = {}
    for s in HEALTH_SYMBOLS:
        bps = _compute_drift_for_symbol(s)
        if bps is None:
            continue
        details[s] = bps
        if bps > max_bps:
            max_bps = bps

    if details:
        _drift_snapshot["symbols"] = details
        _drift_snapshot["last_check_ts"] = now
        _drift_snapshot["max_bps"] = max_bps

    if max_bps >= PRICE_DRIFT_BPS_ALERT and OPS_DRIFT_ALERT_TELEGRAM:
        if _cooldown_ok("drift", now):
            lines = [f"{s}: {bps:.1f}bps" for s, bps in sorted(details.items(), key=lambda x: -x[1]) if bps >= PRICE_DRIFT_BPS_ALERT]
            if lines:
                _tg_send("📐 <b>Price-Drift Alert</b>\n" + "\n".join(lines))

    # Degrade on heavy drift
    if OPS_DRIFT_DEGRADE_ENABLE and max_bps >= OPS_DRIFT_DEGRADE_MIN_BPS:
        _degrade["active"] = True
        _degrade["cap"] = int(OPS_DEGRADE_MAX_LEVERAGE)
        _degrade["reason"] = f"drift>{OPS_DRIFT_DEGRADE_MIN_BPS}bps"
        _degrade["until"] = now + OPS_ALERT_COOLDOWN_SEC
    # auto-clear when cooldown passed and drift low
    if _degrade["active"] and now >= _degrade.get("until", 0):
        # only clear if the latest max drift is below alert threshold (hysteresis)
        if _drift_snapshot.get("max_bps", 0.0) < (OPS_DRIFT_DEGRADE_MIN_BPS * 0.7):
            _degrade.update({"active": False, "cap": None, "reason": "", "until": 0.0})

_last_ops_ts = 0.0
def ops_tick_safe() -> None:
    """נקרא בכל סוף טיק (מ־auto_executor). מבצע בדיקות TTL/Timeout/Drift + Degrade."""
    if not OPS_TICK_ENABLE:
        return
    now = _now()
    global _last_ops_ts
    if now - _last_ops_ts < 0.3:
        # הגנה כפולה אם נקרא פעמיים באותו טיק
        pass
    _check_ttl_and_alert(now)
    _check_timeouts_burst_and_alert(now)
    _check_drift_and_maybe_alert(now)
    _last_ops_ts = now
    # reset tick-local counters
    _exec["timeouts_since_tick"] = 0
    _exec["trades_sent_this_tick"] = 0

# ===== Leverage degrade helpers (לשימוש חיצוני אופציונלי) =====
def get_degrade_cap() -> Optional[int]:
    """אם יש Degrade פעיל – תחזיר cap מומלץ למינוף (e.g., 12). אחרת None."""
    if _degrade.get("active") and _degrade.get("cap"):
        return int(_degrade["cap"])
    return None

def get_last_drift_snapshot() -> Dict[str, Any]:
    return dict(_drift_snapshot)






