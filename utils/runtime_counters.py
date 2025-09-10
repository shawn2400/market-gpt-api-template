# utils/runtime_counters.py
from __future__ import annotations
import os, time, math, json, asyncio, logging
from collections import deque
from typing import Any, Dict, Optional, List, Tuple

logger = logging.getLogger("algogpt.runtime")

# =========================
# ENV / Tunables
# =========================
WINSZ                = int(os.getenv("METRICS_WINDOW_SIZE", "2000"))
WS_LAT_EWMA_ALPHA    = float(os.getenv("WS_LAT_EWMA_ALPHA", "0.2"))
EXEC_TICK_EWMA_ALPHA = float(os.getenv("EXEC_TICK_EWMA_ALPHA", "0.2"))

# Ops / Alerts
OPS_TICK_ENABLE           = os.getenv("OPS_TICK_ENABLE", "1").lower() in ("1","true","on","yes")
STATUS_PRICE_TTL_ALERT_SEC= int(os.getenv("STATUS_PRICE_TTL_ALERT_SEC", "10"))
EXEC_TIMEOUT_BURST_ALERT  = int(os.getenv("EXEC_TIMEOUT_BURST_ALERT", "3"))
PRICE_DRIFT_BPS_ALERT     = float(os.getenv("PRICE_DRIFT_BPS_ALERT", "25"))

OPS_TTL_ALERT_TELEGRAM    = os.getenv("OPS_TTL_ALERT_TELEGRAM", "1") in ("1","true","on","yes")
OPS_TIMEOUT_BURST_TELEGRAM= os.getenv("OPS_TIMEOUT_BURST_TELEGRAM", "1") in ("1","true","on","yes")
OPS_DRIFT_ALERT_TELEGRAM  = os.getenv("OPS_DRIFT_ALERT_TELEGRAM", "1") in ("1","true","on","yes")
OPS_ALERT_COOLDOWN_SEC    = int(os.getenv("OPS_ALERT_COOLDOWN_SEC", "120"))

# Degrade policy
OPS_DEGRADE_MAX_LEVERAGE  = int(os.getenv("OPS_DEGRADE_MAX_LEVERAGE", "12"))
OPS_DRIFT_DEGRADE_ENABLE  = os.getenv("OPS_DRIFT_DEGRADE_ENABLE", "1") in ("1","true","on","yes")
OPS_DRIFT_DEGRADE_MIN_BPS = float(os.getenv("OPS_DRIFT_DEGRADE_MIN_BPS", "30"))
DEGRADE_CLEAR_AFTER_OK    = int(os.getenv("DEGRADE_CLEAR_AFTER_OK", "3"))  # כמה מחזורים תקינים עד ניקוי
DEGRADE_STATUS_TTL_SEC    = int(os.getenv("DEGRADE_STATUS_TTL_SEC", "900"))

# ADX safety + Symbol caps (לא חובה; בשימוש ע"י consumers כמו leverage_policy)
OPS_ADX_SAFETY_MAX_LEVERAGE = int(os.getenv("OPS_ADX_SAFETY_MAX_LEVERAGE", "15"))
_ADX_CUTOFFS = os.getenv("OPS_ADX_LEVERAGE_CUTOFFS", "20,25,30")
try:
    ADX_CUTOFFS = [float(x) for x in _ADX_CUTOFFS.split(",") if x.strip()]
except Exception:
    ADX_CUTOFFS = [20.0, 25.0, 30.0]

# optional JSON envs
try:
    LEVERAGE_SYMBOL_CAPS: Dict[str, int] = json.loads(os.getenv("LEVERAGE_SYMBOL_CAPS", "{}") or "{}")
except Exception:
    LEVERAGE_SYMBOL_CAPS = {}

# health symbols for drift/ttl checks
HEALTH_SYMBOLS = [s.strip().upper() for s in os.getenv("HEALTH_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]

# Telegram
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID_STR = (os.getenv("TELEGRAM_CHAT_ID", "").strip() or os.getenv("ADMIN_CHAT_ID", "").strip())
CHAT_ID     = int(CHAT_ID_STR) if CHAT_ID_STR.isdigit() else None
TG_API      = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
TG_ENABLED  = bool(BOT_TOKEN and CHAT_ID)

# =========================
# Optional price freshness source
# =========================
try:
    from utils.ws_fallback import is_price_fresh as ws_is_fresh
except Exception:
    ws_is_fresh = None  # type: ignore

# =========================
# Binance client deps (mark/index/price)
# =========================
try:
    from utils.binance_client import futures_mark_price, futures_index_price
except Exception:
    futures_mark_price = None  # type: ignore
    futures_index_price = None  # type: ignore

# =========================
# State: WS metrics
# =========================
_ws_up: bool = False
_ws_last_change_ts: float = 0.0
_ws_reconnects_total: int = 0
_ws_ewma_ms: Optional[float] = None
_ws_last_lat_ms: Optional[float] = None

# =========================
# State: Executor metrics
# =========================
_tick_ewma_ms: Optional[float] = None
_tick_last_ms: Optional[float] = None
_tick_samples: deque[float] = deque(maxlen=WINSZ)

_timeouts_ts: deque[float] = deque(maxlen=WINSZ)
_current_interval: int = 0
_no_trade_streak: int = 0

# =========================
# State: Ops / Alerts / Drift
# =========================
_last_alert_ts: Dict[str, float] = {}
_last_ttl_bad: Dict[str, bool] = {s: False for s in HEALTH_SYMBOLS}
_last_drift_bps: Dict[str, float] = {s: 0.0 for s in HEALTH_SYMBOLS}
_last_drift_bad: bool = False
_drift_ok_streak: int = 0

# Degrade status
_degrade_active: bool = False
_degrade_since_ts: float = 0.0
_degrade_cap: Optional[int] = None

# =========================
# Helpers
# =========================
def _ewma(prev: Optional[float], x: float, alpha: float) -> float:
    return x if prev is None else (alpha * x + (1.0 - alpha) * prev)

def _pct_to_bps(frac: float) -> float:
    return frac * 10000.0

def _now() -> float:
    return time.time()

def _cooldown_ok(key: str) -> bool:
    t = _last_alert_ts.get(key, 0.0)
    return (_now() - t) >= OPS_ALERT_COOLDOWN_SEC

def _touch_cooldown(key: str) -> None:
    _last_alert_ts[key] = _now()

async def _tg_send_async(text: str) -> None:
    if not TG_ENABLED: return
    import httpx  # local import
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(f"{TG_API}/sendMessage", data={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            })
    except Exception as e:
        logger.warning({"event":"tg_send_failed","err":str(e)})

def _notify_tg(key: str, text: str, force: bool=False) -> None:
    if not TG_ENABLED: return
    if not force and not _cooldown_ok(key): return
    _touch_cooldown(key)
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_tg_send_async(text))
    except RuntimeError:
        # No running loop (unlikely here) — best effort sync
        asyncio.run(_tg_send_async(text))

# =========================
# Public WS hooks
# =========================
def ws_note_event(*, latency_ms: Optional[float]) -> None:
    """Record a single WS event: update EWMA latency."""
    global _ws_ewma_ms, _ws_last_lat_ms
    if latency_ms is None:
        return
    _ws_last_lat_ms = float(latency_ms)
    _ws_ewma_ms = _ewma(_ws_ewma_ms, float(latency_ms), WS_LAT_EWMA_ALPHA)

def ws_note_reconnect() -> None:
    """Bump reconnects counter."""
    global _ws_reconnects_total
    _ws_reconnects_total += 1

def ws_note_up(up: bool) -> None:
    """Mark WS up/down & timestamp."""
    global _ws_up, _ws_last_change_ts
    if _ws_up != bool(up):
        _ws_up = bool(up)
        _ws_last_change_ts = _now()

# =========================
# Public EXEC hooks
# =========================
def exec_on_batch_timeout() -> None:
    """Called when a scan batch timed out."""
    _timeouts_ts.append(_now())

def exec_on_trade_sent(symbol: str) -> None:
    """Optional hook when a trade is sent (no-op stats side)."""
    # place to extend KPIs by symbol if needed
    pass

def exec_on_tick_stop(*, dt_ms: float, current_interval: int, no_trade_streak: int) -> None:
    """Called at the end of an executor tick; records dt and surfaces EWMA/p95/p99."""
    global _tick_ewma_ms, _tick_last_ms, _current_interval, _no_trade_streak
    dt_ms = float(max(0.0, dt_ms))
    _tick_last_ms = dt_ms
    _tick_ewma_ms = _ewma(_tick_ewma_ms, dt_ms, EXEC_TICK_EWMA_ALPHA)
    _tick_samples.append(dt_ms)
    _current_interval = int(current_interval)
    _no_trade_streak = int(no_trade_streak)

# =========================
# Stats / percentiles
# =========================
def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s)-1) * (p/100.0)
    f = math.floor(k); c = math.ceil(k)
    if f == c:
        return float(s[int(k)])
    return float(s[int(f)] * (c-k) + s[int(c)] * (k-f))

def _timeouts_recent_count(window_sec: int = 180) -> int:
    now = _now()
    while _timeouts_ts and (now - _timeouts_ts[0]) > window_sec:
        _timeouts_ts.popleft()
    return len(_timeouts_ts)

# =========================
# Drift / TTL logic
# =========================
def _calc_drift_bps(symbol: str) -> Optional[float]:
    """Return absolute drift bps between MARK and INDEX prices for symbol."""
    if not futures_mark_price or not futures_index_price:
        return None
    try:
        mark = futures_mark_price(symbol)  # float or None
        index = futures_index_price(symbol)
        if not mark or not index or index <= 0:
            return None
        drift = abs(mark - index) / index
        return _pct_to_bps(drift)
    except Exception as e:
        logger.debug({"event":"drift_calc_failed","symbol":symbol,"err":str(e)})
        return None

def _ttl_bad(symbol: str) -> bool:
    """If ws freshness is available — use its TTL; else consider OK."""
    if ws_is_fresh is None:
        return False
    try:
        ok = ws_is_fresh(symbol, STATUS_PRICE_TTL_ALERT_SEC)
        return not bool(ok)
    except Exception:
        return False

# =========================
# Ops tick (alerts+degrade)
# =========================
def ops_tick_safe() -> None:
    """Runs cheap health checks and sends ops alerts under cooldown; also manages leverage degrade."""
    if not OPS_TICK_ENABLE:
        return

    # 1) TTL alerts per symbol (ws freshness only if available)
    if OPS_TTL_ALERT_TELEGRAM and ws_is_fresh is not None and STATUS_PRICE_TTL_ALERT_SEC > 0:
        for s in HEALTH_SYMBOLS:
            bad = _ttl_bad(s)
            was_bad = _last_ttl_bad.get(s, False)
            _last_ttl_bad[s] = bad
            if bad and not was_bad:
                _notify_tg(
                    key=f"ttl:{s}",
                    text=f"⚠️ <b>TTL Alert</b> — {s}: המחיר אינו מעודכן מעל {STATUS_PRICE_TTL_ALERT_SEC}s",
                )

    # 2) Timeout burst alert (executor)
    if OPS_TIMEOUT_BURST_TELEGRAM and EXEC_TIMEOUT_BURST_ALERT > 0:
        cnt = _timeouts_recent_count()
        if cnt >= EXEC_TIMEOUT_BURST_ALERT and _cooldown_ok("exec:burst"):
            _notify_tg(
                key="exec:burst",
                text=(f"⏱️ <b>Timeout Burst</b> — {cnt} timeouts אחרונים. "
                      f"tick_ewma≈{_tick_ewma_ms:.0f}ms, last≈{(_tick_last_ms or 0):.0f}ms, "
                      f"interval={_current_interval}s, streak={_no_trade_streak}"),
            )

    # 3) Price drift alert + degrade
    max_drift: float = 0.0
    drift_any_bad = False
    if PRICE_DRIFT_BPS_ALERT > 0 and OPS_DRIFT_ALERT_TELEGRAM:
        for s in HEALTH_SYMBOLS:
            d = _calc_drift_bps(s)
            if d is None:
                continue
            _last_drift_bps[s] = d
            max_drift = max(max_drift, d)
            if d >= PRICE_DRIFT_BPS_ALERT:
                drift_any_bad = True

        if drift_any_bad and _cooldown_ok("drift:max"):
            _notify_tg(
                key="drift:max",
                text=("📉 <b>Price-Drift Alert</b> — חריגת drift MARK↔INDEX\n" +
                      ", ".join(f"{sym}:{_last_drift_bps.get(sym,0):.1f}bps" for sym in HEALTH_SYMBOLS))
            )

    # Degrade policy activation/clear
    _apply_degrade_policy(max_drift_bps=max_drift)

# =========================
# Degrade policy core
# =========================
def _apply_degrade_policy(*, max_drift_bps: float) -> None:
    global _degrade_active, _degrade_since_ts, _degrade_cap, _drift_ok_streak

    if not OPS_DRIFT_DEGRADE_ENABLE:
        return

    # Activate degrade on large drift
    if max_drift_bps >= OPS_DRIFT_DEGRADE_MIN_BPS:
        if not _degrade_active:
            _degrade_active = True
            _degrade_since_ts = _now()
            _degrade_cap = int(OPS_DEGRADE_MAX_LEVERAGE)
            _drift_ok_streak = 0
            _notify_tg("degrade:on",
                       f"🔻 <b>Degrade ON</b> — Drift {max_drift_bps:.1f}bps ≥ {OPS_DRIFT_DEGRADE_MIN_BPS}bps. "
                       f"Max leverage capped to {OPS_DEGRADE_MAX_LEVERAGE}x.")
        else:
            _degrade_since_ts = _now()  # refresh activity
        return

    # When drift normalizes — count “OK” streak and clear once stable
    if _degrade_active:
        _drift_ok_streak += 1
        # Clear by time or by consecutive ok cycles
        if (_now() - _degrade_since_ts) >= DEGRADE_STATUS_TTL_SEC or _drift_ok_streak >= DEGRADE_CLEAR_AFTER_OK:
            _notify_tg("degrade:off", "✅ <b>Degrade OFF</b> — Drift חזר לתקין. משחרר קאפ מינוף.")
            _degrade_active = False
            _degrade_since_ts = 0.0
            _degrade_cap = None
            _drift_ok_streak = 0

# =========================
# Leverage caps exposure
# =========================
def current_leverage_cap(symbol: Optional[str]=None, adx: Optional[float]=None) -> Optional[int]:
    """
    חשיפת קאפ מינוף גלובלי/ספציפי לפי:
    1) קאפ פר-סימבול (LEVERAGE_SYMBOL_CAPS)
    2) Degrade עקב Drift (OPS_DEGRADE_MAX_LEVERAGE כשה־degrade פעיל)
    3) ADX safety cap (OPS_ADX_SAFETY_MAX_LEVERAGE) עבור ADX נמוך
    מחזיר את המינימום מתוך כל הקאפים הפעילים, או None אם אין קאפ.
    """
    caps: List[int] = []

    # 1) symbol cap
    if symbol:
        cap_sym = LEVERAGE_SYMBOL_CAPS.get(symbol.upper())
        if isinstance(cap_sym, int) and cap_sym > 0:
            caps.append(int(cap_sym))

    # 2) degrade cap
    if _degrade_active and _degrade_cap:
        caps.append(int(_degrade_cap))

    # 3) ADX safety (אם ADX סופק, חלים רק בתנאי ADX נמוך יחסית)
    if adx is not None and ADX_CUTOFFS:
        try:
            # אם ADX קטן מהסף הראשון — אל תתפרע; הגבול העליון יהיה OPS_ADX_SAFETY_MAX_LEVERAGE
            if float(adx) < float(ADX_CUTOFFS[0]):
                caps.append(int(OPS_ADX_SAFETY_MAX_LEVERAGE))
        except Exception:
            pass

    if not caps:
        return None
    return int(max(1, min(caps)))

# =========================
# Status surfaces (routers can use)
# =========================
def ws_status() -> Dict[str, Any]:
    return {
        "ws_up": bool(_ws_up),
        "ws_ewma_latency_ms": float(_ws_ewma_ms or 0.0),
        "ws_last_latency_ms": float(_ws_last_lat_ms or 0.0),
        "ws_reconnects_total": int(_ws_reconnects_total),
        "ws_last_change_ts": float(_ws_last_change_ts or 0.0),
    }

def executor_status() -> Dict[str, Any]:
    vals = list(_tick_samples)
    p95 = _percentile(vals, 95.0) if vals else 0.0
    p99 = _percentile(vals, 99.0) if vals else 0.0
    return {
        "tick_ewma_ms": float(_tick_ewma_ms or 0.0),
        "tick_last_ms": float(_tick_last_ms or 0.0),
        "tick_p95_ms": float(p95),
        "tick_p99_ms": float(p99),
        "timeouts_recent_count": int(_timeouts_recent_count()),
        "current_interval": int(_current_interval),
        "no_trade_streak": int(_no_trade_streak),
    }

def ops_status() -> Dict[str, Any]:
    return {
        "ttl_bad": {s: bool(_last_ttl_bad.get(s, False)) for s in HEALTH_SYMBOLS},
        "drift_bps": {s: float(_last_drift_bps.get(s, 0.0)) for s in HEALTH_SYMBOLS},
        "degrade_active": bool(_degrade_active),
        "degrade_cap": int(_degrade_cap or 0) if _degrade_active and _degrade_cap else None,
        "last_alerts": dict(_last_alert_ts),
    }





