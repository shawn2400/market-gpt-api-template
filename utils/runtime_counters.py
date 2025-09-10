# utils/runtime_counters.py
from __future__ import annotations
import os, time, logging, math
from collections import deque
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger("algogpt.runtime")

# =======================
# Env
# =======================
ALPHA_WS  = float(os.getenv("WS_LAT_EWMA_ALPHA",  "0.2"))
ALPHA_EXEC= float(os.getenv("EXEC_TICK_EWMA_ALPHA","0.2"))

TTL_ALERT_SEC           = int(os.getenv("STATUS_PRICE_TTL_ALERT_SEC", "10"))
TIMEOUT_BURST_ALERT     = int(os.getenv("EXEC_TIMEOUT_BURST_ALERT", "3"))
OPS_TICK_ENABLE         = os.getenv("OPS_TICK_ENABLE","1").lower() in ("1","true","on","yes")

DRIFT_BPS_ALERT         = float(os.getenv("PRICE_DRIFT_BPS_ALERT","25"))
DRIFT_DEGRADE_ENABLE    = os.getenv("OPS_DRIFT_DEGRADE_ENABLE","1").lower() in ("1","true","on","yes")
DRIFT_DEGRADE_MIN_BPS   = float(os.getenv("OPS_DRIFT_DEGRADE_MIN_BPS","30"))

OPS_TTL_ALERT_TELEGRAM      = os.getenv("OPS_TTL_ALERT_TELEGRAM","1").lower() in ("1","true","on","yes")
OPS_TIMEOUT_BURST_TELEGRAM  = os.getenv("OPS_TIMEOUT_BURST_TELEGRAM","1").lower() in ("1","true","on","yes")
OPS_DRIFT_ALERT_TELEGRAM    = os.getenv("OPS_DRIFT_ALERT_TELEGRAM","0").lower() in ("1","true","on","yes")
OPS_ALERT_COOLDOWN_SEC      = int(os.getenv("OPS_ALERT_COOLDOWN_SEC", "120"))

DEGRADE_MAX_LEV         = int(os.getenv("OPS_DEGRADE_MAX_LEVERAGE","12"))
ADX_SAFETY_MAX_LEV      = int(os.getenv("OPS_ADX_SAFETY_MAX_LEVERAGE","15"))

HEALTH_SYMBOLS = [s.strip().upper() for s in os.getenv("HEALTH_SYMBOLS","BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]

# =======================
# Telegram helper (soft)
# =======================
async def _notify_tg(msg: str) -> None:
    try:
        from utils.telegram_notifier import notify_ops_alert  # preferred
        await notify_ops_alert(msg)
        return
    except Exception:
        pass
    try:
        from utils.telegram_notifier import notify_scan_error  # fallback
        await notify_scan_error(msg)
    except Exception:
        logger.info({"event":"ops.alert", "msg": msg})

# cooldowns
_last_alert_ts: Dict[str,float] = {}
def _cooldown_ok(key: str, cool_s: int) -> bool:
    now = time.time()
    ts  = _last_alert_ts.get(key, 0.0)
    if now - ts >= cool_s:
        _last_alert_ts[key] = now
        return True
    return False

# =======================
# WS-User counters & hooks
# =======================
_ws_running = False
_ws_reconnects = 0
_ws_last_event_ts: Optional[float] = None
_ws_ewma_inter_ms: Optional[float] = None

def ws_on_connect():
    global _ws_running
    _ws_running = True

def ws_on_disconnect():
    global _ws_running
    _ws_running = False

def ws_on_reconnect():
    global _ws_reconnects
    _ws_reconnects += 1

def ws_on_event(latency_ms: Optional[float] = None):
    global _ws_last_event_ts, _ws_ewma_inter_ms
    now = time.time()
    if _ws_last_event_ts:
        inter_ms = (now - _ws_last_event_ts) * 1000.0
        if _ws_ewma_inter_ms is None:
            _ws_ewma_inter_ms = inter_ms
        else:
            _ws_ewma_inter_ms = (1.0 - ALPHA_WS) * _ws_ewma_inter_ms + ALPHA_WS * inter_ms
    _ws_last_event_ts = now

def ws_user_status() -> Dict[str, Any]:
    ttl = None
    if _ws_last_event_ts:
        ttl = max(0.0, time.time() - _ws_last_event_ts)
    return {
        "running": bool(_ws_running),
        "reconnects": int(_ws_reconnects),
        "last_event_ts": int(_ws_last_event_ts or 0),
        "ttl_sec": round(ttl or 0.0, 3),
        "inter_event_ewma_ms": round(_ws_ewma_inter_ms or 0.0, 3),
    }

# =======================
# Executor counters
# =======================
_exec_last_tick_ms: Optional[float] = None
_exec_ewma_ms: Optional[float] = None
_exec_last_tick_ts: Optional[float] = None
_exec_no_trade_streak: int = 0
_exec_current_interval: int = int(os.getenv("SCAN_INTERVAL","60"))

# timeouts rolling window
_timeout_events: deque[float] = deque(maxlen=512)

def exec_on_batch_timeout():
    _timeout_events.append(time.time())

def exec_on_trade_sent(symbol: str):
    # reserved for future per-symbol counters
    pass

def exec_on_tick_stop(dt_ms: float, current_interval: int, no_trade_streak: int):
    global _exec_last_tick_ms, _exec_ewma_ms, _exec_last_tick_ts, _exec_current_interval, _exec_no_trade_streak
    _exec_last_tick_ms = float(dt_ms)
    _exec_last_tick_ts = time.time()
    _exec_current_interval = int(current_interval)
    _exec_no_trade_streak = int(no_trade_streak)
    if _exec_ewma_ms is None:
        _exec_ewma_ms = _exec_last_tick_ms
    else:
        _exec_ewma_ms = (1.0 - ALPHA_EXEC) * _exec_ewma_ms + ALPHA_EXEC * _exec_last_tick_ms

def executor_status() -> Dict[str, Any]:
    burst_60s = sum(1 for t in _timeout_events if t >= time.time() - 60)
    return {
        "last_tick_ms": round(_exec_last_tick_ms or 0.0, 3),
        "tick_ewma_ms": round(_exec_ewma_ms or 0.0, 3),
        "last_tick_ts": int(_exec_last_tick_ts or 0),
        "timeouts_last_60s": int(burst_60s),
        "current_interval_sec": int(_exec_current_interval),
        "no_trade_streak": int(_exec_no_trade_streak),
    }

# =======================
# Dynamic leverage cap (Degrade/Bump)
# =======================
_degrade_active = False
_dynamic_max_lev: Optional[int] = None

def ops_gate_degrade_active(enable: bool = True, *, cap_leverage: Optional[int] = None):
    """Enable/disable degrade mode; optional leverage cap."""
    global _degrade_active, _dynamic_max_lev
    _degrade_active = bool(enable)
    if enable:
        _dynamic_max_lev = int(cap_leverage or DEGRADE_MAX_LEV)
    else:
        _dynamic_max_lev = None
    logger.warning({"event":"ops.degrade", "active": _degrade_active, "max_lev": _dynamic_max_lev})

def ops_gate_bump():
    """Cancel degrade & restore caps."""
    ops_gate_degrade_active(False)

def get_current_max_leverage(default_max: int) -> int:
    if _dynamic_max_lev is None:
        return int(default_max)
    return int(max(1, min(_dynamic_max_lev, default_max)))

# =======================
# Price-Feed TTL helper (best-effort)
# =======================
def _get_ws_price_ttl_sec() -> float:
    """
    עדיפות: utils.ws_fallback.get_last_ts() לכל אחד מה-HEALTH_SYMBOLS.
    אם לא קיים – נשתמש ב-WS last_event כ-approx.
    """
    try:
        from utils import ws_fallback  # type: ignore
        now = time.time()
        ttls: List[float] = []
        for sym in HEALTH_SYMBOLS:
            try:
                ts = float(ws_fallback.get_last_ts(sym))  # expected helper
                if ts > 0:
                    ttls.append(max(0.0, now - ts))
            except Exception:
                pass
        if ttls:
            return max(ttls)  # worst ttl
    except Exception:
        pass
    # fallback: based on account WS activity
    if _ws_last_event_ts:
        return max(0.0, time.time() - _ws_last_event_ts)
    return 1e9  # no data

# =======================
# Drift (Mark vs Index)
# =======================
def _index_price(symbol: str) -> Optional[float]:
    """
    עדיפות: utils.binance_client.futures_index_price
    פallback: client.futures_premium_index() דרך get_futures_client()
    """
    try:
        from utils.binance_client import futures_index_price as _fip  # type: ignore
        p = _fip(symbol)
        if p and p > 0:
            return float(p)
    except Exception:
        pass
    # fallback via client
    try:
        from utils.binance_client import get_futures_client  # type: ignore
        c = get_futures_client()
        data = c.futures_premium_index(symbol=symbol.upper())
        p = float(data.get("indexPrice"))
        if p > 0:
            return p
    except Exception:
        return None
    return None

def _mark_price(symbol: str) -> Optional[float]:
    try:
        from utils.binance_client import futures_mark_price  # type: ignore
        return futures_mark_price(symbol)
    except Exception:
        return None

def _check_price_drift() -> Tuple[float, Optional[str], Optional[float], Optional[float]]:
    """
    מחזיר: (max_drift_bps, symbol, mark, index)
    """
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

# =======================
# Ops tick (called every scan loop)
# =======================
def _count_timeouts_last_60s() -> int:
    now = time.time()
    return sum(1 for t in _timeout_events if t >= now - 60)

def _fmt_bps(x: float) -> str:
    return f"{x:.1f}bps"

def _fmt_pct(x: float) -> str:
    return f"{x:.3f}%"

def _fmt_price(x: Optional[float]) -> str:
    return "NA" if x is None else f"{x:.6f}"

def ops_tick_safe():
    if not OPS_TICK_ENABLE:
        return
    # --- TTL alert
    try:
        ttl = _get_ws_price_ttl_sec()
        if OPS_TTL_ALERT_TELEGRAM and ttl > TTL_ALERT_SEC and _cooldown_ok("ttl", OPS_ALERT_COOLDOWN_SEC):
            import asyncio
            asyncio.create_task(_notify_tg(f"⚠️ TTL Alert: price_feed ttl={ttl:.1f}s > {TTL_ALERT_SEC}s"))
    except Exception as e:
        logger.debug({"event":"ops.ttl_check_err", "err": str(e)})

    # --- Timeout burst alert
    try:
        burst = _count_timeouts_last_60s()
        if OPS_TIMEOUT_BURST_TELEGRAM and burst >= TIMEOUT_BURST_ALERT and _cooldown_ok("timeout_burst", OPS_ALERT_COOLDOWN_SEC):
            import asyncio
            asyncio.create_task(_notify_tg(f"⏱️ Timeout Burst: last_60s={burst} (≥{TIMEOUT_BURST_ALERT})"))
    except Exception as e:
        logger.debug({"event":"ops.timeout_check_err", "err": str(e)})

    # --- Price Drift alert (+ optional degrade)
    try:
        max_bps, sym, mrk, idx = _check_price_drift()
        if sym and max_bps >= DRIFT_BPS_ALERT:
            if OPS_DRIFT_ALERT_TELEGRAM and _cooldown_ok("drift", OPS_ALERT_COOLDOWN_SEC):
                import asyncio
                asyncio.create_task(_notify_tg(
                    f"📉 Price-Drift: {sym} | drift={_fmt_bps(max_bps)} "
                    f"(mark={_fmt_price(mrk)} vs index={_fmt_price(idx)}) | thr={_fmt_bps(DRIFT_BPS_ALERT)}"
                ))
            # degrade policy
            if DRIFT_DEGRADE_ENABLE and max_bps >= max(DRIFT_BPS_ALERT, DRIFT_DEGRADE_MIN_BPS) and not _degrade_active:
                ops_gate_degrade_active(True, cap_leverage=DEGRADE_MAX_LEV)
                logger.warning({"event":"ops.degrade_by_drift", "symbol": sym, "bps": round(max_bps,1), "cap": DEGRADE_MAX_LEV})
    except Exception as e:
        logger.debug({"event":"ops.drift_check_err", "err": str(e)})

# =======================
# Back-compat no-ops
# (so imports from other modules won't fail if missing)
# =======================
__all__ = [
    "exec_on_batch_timeout", "exec_on_trade_sent", "exec_on_tick_stop", "executor_status",
    "ws_on_connect", "ws_on_disconnect", "ws_on_reconnect", "ws_on_event", "ws_user_status",
    "ops_tick_safe", "ops_gate_degrade_active", "ops_gate_bump", "get_current_max_leverage",
]




