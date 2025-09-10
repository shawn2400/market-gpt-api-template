# utils/runtime_counters.py
from __future__ import annotations
import os, time, threading
from collections import deque
from typing import Dict, Any, Optional

# טלגרם (אופציונלי)
try:
    from utils.telegram_notifier import notify_info as _tg_info, notify_error as _tg_err
except Exception:
    async def _tg_info(*a, **k): return None
    async def _tg_err(*a, **k): return None

def _env_float(k: str, d: float) -> float:
    try: return float(os.getenv(k, str(d)))
    except Exception: return d

def _env_int(k: str, d: int) -> int:
    try: return int(os.getenv(k, str(d)))
    except Exception: return d

def _env_bool(k: str, dflt: bool) -> bool:
    v = os.getenv(k, str(int(dflt)))
    return str(v).strip().lower() in ("1","true","yes","on")

class _EWMA:
    def __init__(self, alpha: float):
        self.alpha = max(0.01, min(1.0, float(alpha)))
        self.v: Optional[float] = None
    def update(self, x: float):
        x = float(x)
        self.v = x if self.v is None else (self.alpha*x + (1.0-self.alpha)*self.v)
    def get(self) -> float:
        return float(self.v if self.v is not None else 0.0)

# ===================== WS User counters =====================
class _WSCounters:
    def __init__(self):
        self.boot_ts = int(time.time())
        self._lock = threading.Lock()
        self.connected = False
        self.reconnects = 0
        self.messages_total = 0
        self.errors_total = 0
        self.last_event_ts: float = 0.0
        self.last_error: Optional[str] = None
        self.last_latency_ms: float = 0.0
        self.lat_ewma = _EWMA(_env_float("WS_LAT_EWMA_ALPHA", 0.2))
        self.last_price_ts: Dict[str, float] = {}
        self.last_price_symbol: Optional[str] = None

        # Drift state (mark vs index)
        self.drift_supported = False
        self.drift_bps_max: float = 0.0
        self.drift_alert: bool = False

        # Degrade suggestion (WS noisy)
        self.degrade_suggested: bool = False

    # --- Mutations from WS code ---
    def on_connect(self):
        with self._lock:
            self.connected = True
            self.last_event_ts = time.time()

    def on_disconnect(self):
        with self._lock:
            self.connected = False
            self.last_event_ts = time.time()

    def on_reconnect(self):
        with self._lock:
            self.reconnects += 1
            self.connected = True
            self.last_event_ts = time.time()

    def on_message(self, latency_ms: float):
        with self._lock:
            self.messages_total += 1
            self.last_event_ts = time.time()
            self.last_latency_ms = float(latency_ms)
            self.lat_ewma.update(self.last_latency_ms)

    def on_price(self, symbol: str):
        ts = time.time()
        with self._lock:
            self.last_price_ts[symbol.upper()] = ts
            self.last_price_symbol = symbol.upper()
            self.last_event_ts = ts

    def on_error(self, err: str):
        with self._lock:
            self.errors_total += 1
            self.last_error = str(err)
            self.last_event_ts = time.time()

    # --- Read ---
    def status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            latest_sym, latest_ts = None, 0.0
            if self.last_price_ts:
                latest_sym, latest_ts = max(self.last_price_ts.items(), key=lambda kv: kv[1])
            ttl_sec = (now - latest_ts) if latest_ts > 0 else None
            return {
                "boot_ts": self.boot_ts,
                "connected": self.connected,
                "reconnects": self.reconnects,
                "messages_total": self.messages_total,
                "errors_total": self.errors_total,
                "last_event_ts": self.last_event_ts,
                "last_error": self.last_error,
                "latency_ms": {
                    "last": round(self.last_latency_ms, 2),
                    "ewma": round(self.lat_ewma.get(), 2),
                },
                "price_feed": {
                    "latest_symbol": latest_sym,
                    "latest_ts": latest_ts,
                    "ttl_sec": round(ttl_sec, 3) if ttl_sec is not None else None,
                },
                "price_drift": {
                    "supported": self.drift_supported,
                    "max_bps": round(self.drift_bps_max, 2),
                    "alert": self.drift_alert,
                },
                "degrade": {
                    "suggested": bool(self.degrade_suggested)
                }
            }

# ===================== Executor counters =====================
class _ExecCounters:
    def __init__(self):
        self.boot_ts = int(time.time())
        self._lock = threading.Lock()
        self.last_tick_ts: float = 0.0
        self.last_tick_ms: float = 0.0
        self.tick_ewma = _EWMA(_env_float("EXEC_TICK_EWMA_ALPHA", 0.2))
        self.batch_timeouts_total = 0
        self._timeouts_ts: deque[float] = deque(maxlen=1000)
        self.trades_sent_total = 0
        self.last_trade_symbol: Optional[str] = None
        self.last_trade_ts: float = 0.0
        self.no_trade_streak = 0
        self.scan_interval_current = _env_int("SCAN_INTERVAL", 60)
        self.time_budget_ms = int(_env_float("SCAN_TIME_BUDGET_SEC", 7.5) * 1000)

    def on_tick_stop(self, dt_ms: float, current_interval: int, no_trade_streak: int):
        with self._lock:
            self.last_tick_ts = time.time()
            self.last_tick_ms = float(dt_ms)
            self.tick_ewma.update(self.last_tick_ms)
            self.scan_interval_current = int(current_interval)
            self.no_trade_streak = int(no_trade_streak)

    def on_batch_timeout(self):
        with self._lock:
            self.batch_timeouts_total += 1
            self._timeouts_ts.append(time.time())

    def on_trade_sent(self, symbol: str):
        with self._lock:
            self.trades_sent_total += 1
            self.last_trade_symbol = symbol.upper()
            self.last_trade_ts = time.time()

    def status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            timeouts_60s = sum(1 for t in self._timeouts_ts if now - t <= 60)
            timeouts_5m  = sum(1 for t in self._timeouts_ts if now - t <= 300)
            return {
                "boot_ts": self.boot_ts,
                "last_tick_ts": self.last_tick_ts,
                "tick_ms": {
                    "last": round(self.last_tick_ms, 2),
                    "ewma": round(self.tick_ewma.get(), 2),
                    "budget_ms": self.time_budget_ms,
                },
                "timeouts": {
                    "total": self.batch_timeouts_total,
                    "last_60s": timeouts_60s,
                    "last_5m": timeouts_5m,
                },
                "trades": {
                    "sent_total": self.trades_sent_total,
                    "last_symbol": self.last_trade_symbol,
                    "last_ts": self.last_trade_ts,
                },
                "scheduler": {
                    "scan_interval_current": self.scan_interval_current,
                    "no_trade_streak": self.no_trade_streak,
                },
            }

# ===================== Ops Guard (Drift + TTL + Burst) =====================
class _Ops:
    def __init__(self, ws: _WSCounters):
        self.ws = ws
        self.enabled = _env_bool("OPS_TICK_ENABLE", True)

        # Drift
        self.drift_thr_bps = _env_float("PRICE_DRIFT_BPS_ALERT", 25.0)
        self._last_drift_alert_ts: float = 0.0
        self._drift_alert_ttl_sec = 120.0

        # TTL Alert
        self.ttl_thr_sec = _env_float("STATUS_PRICE_TTL_ALERT_SEC", 10.0)
        self._last_ttl_alert_ts = 0.0
        self._ttl_alert_ttl_sec = 90.0

        # Timeout Burst (executor)
        self.timeout_burst_thr = _env_int("EXEC_TIMEOUT_BURST_ALERT", 3)
        self._last_burst_alert_ts = 0.0
        self._burst_alert_ttl_sec = 120.0

        # Backpressure hint & degrade suggestion
        self._last_bp_hint_ts = 0.0
        self._bp_hint_ttl_sec = 120.0

        try:
            # נשתמש רק אם יש Mark+Index
            from utils.binance_client import futures_mark_price, futures_index_price  # type: ignore
            self._mark = futures_mark_price  # type: ignore
            self._index = futures_index_price  # type: ignore
            self.ws.drift_supported = True
        except Exception:
            self._mark = None
            self._index = None
            self.ws.drift_supported = False

        self.health_symbols = [s.strip().upper() for s in os.getenv("HEALTH_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]

    def _check_price_drift(self):
        if not (self._mark and self._index):
            return
        now = time.time()
        max_bps = 0.0
        for sym in self.health_symbols:
            try:
                m = float(self._mark(sym) or 0.0)
                i = float(self._index(sym) or 0.0)
                if m > 0 and i > 0:
                    bps = abs(m - i) / i * 10000.0
                    if bps > max_bps:
                        max_bps = bps
            except Exception:
                continue

        self.ws.drift_bps_max = max_bps
        self.ws.drift_alert = bool(max_bps >= self.drift_thr_bps)
        if self.ws.drift_alert and now - self._last_drift_alert_ts > self._drift_alert_ttl_sec:
            try:
                import asyncio
                asyncio.create_task(_tg_err(f"⚠️ Price Drift high: {max_bps:.1f} bps. מומלץ להפעיל FEAT_MARK_INDEX_SANITY / לעבוד Mark-only זמנית."))
            except Exception:
                pass
            self._last_drift_alert_ts = now
            self.ws.degrade_suggested = True

    def _check_price_ttl(self):
        # מפיק TTL על סמך ה־latest tick מכל הסימבולים
        st = self.ws.status()
        ttl = st.get("price_feed", {}).get("ttl_sec")
        if ttl is None:
            return
        now = time.time()
        if ttl > self.ttl_thr_sec and now - self._last_ttl_alert_ts > self._ttl_alert_ttl_sec:
            try:
                import asyncio
                asyncio.create_task(_tg_err(f"⏱️ Price TTL high: {ttl:.1f}s (>{self.ttl_thr_sec:.1f}s). מומלץ לעבור זמנית Mark-only ולהדליק Sanity checks ל־WS."))
            except Exception:
                pass
            self._last_ttl_alert_ts = now
            self.ws.degrade_suggested = True

    def _check_timeout_burst(self):
        # מציץ בסטטוס ה־Executor (מייצר אותו כאן באופן מקומי)
        st = get_exec_status()
        last_60 = st.get("status", st).get("timeouts", {}).get("last_60s", 0)
        tick = st.get("status", st).get("tick_ms", {})
        ewma = float(tick.get("ewma") or 0.0)
        budget = float(tick.get("budget_ms") or 0.0)

        now = time.time()
        if last_60 >= self.timeout_burst_thr and now - self._last_burst_alert_ts > self._burst_alert_ttl_sec:
            try:
                import asyncio
                asyncio.create_task(_tg_err(f"🚨 Timeout burst: {last_60} timeouts ב־60ש׳. tick_ewma={ewma:.0f}ms budget={budget:.0f}ms. שקול להגדיל SCAN_INTERVAL / להוריד SCAN_CONCURRENCY."))
            except Exception:
                pass
            self._last_burst_alert_ts = now

        # Backpressure hint אם ewma חורג משמעותית מה־budget
        if budget > 0 and ewma > 1.3 * budget and now - self._last_bp_hint_ts > self._bp_hint_ttl_sec:
            try:
                import asyncio
                asyncio.create_task(_tg_info(f"ℹ️ Backpressure: tick EWMA {ewma:.0f}ms > budget {budget:.0f}ms. Auto-Tune יאט בסבבים הבאים; אפשר גם לשפר ידנית את SCAN_INTERVAL."))
            except Exception:
                pass
            self._last_bp_hint_ts = now

    def tick(self):
        if not self.enabled:
            return
        # בדיקות קלילות, בלי לולאות כבדות
        self._check_price_drift()
        self._check_price_ttl()
        self._check_timeout_burst()

# ========= Singletons & Facade =========
_WS = _WSCounters()
_EXEC = _ExecCounters()
_OPS = _Ops(_WS)

# ---- Facade for imports ----
def ws_on_connect(): _WS.on_connect()
def ws_on_disconnect(): _WS.on_disconnect()
def ws_on_reconnect(): _WS.on_reconnect()
def ws_on_message_latency_ms(ms: float): _WS.on_message(ms)
def ws_on_price(symbol: str): _WS.on_price(symbol)
def ws_on_error(err: str): _WS.on_error(err)

def exec_on_tick_stop(dt_ms: float, current_interval: int, no_trade_streak: int): _EXEC.on_tick_stop(dt_ms, current_interval, no_trade_streak)
def exec_on_batch_timeout(): _EXEC.on_batch_timeout()
def exec_on_trade_sent(symbol: str): _EXEC.on_trade_sent(symbol)

def ops_tick_safe():
    try: _OPS.tick()
    except Exception: pass

def get_ws_status() -> Dict[str, Any]:
    return _WS.status()

def get_exec_status() -> Dict[str, Any]:
    return _EXEC.status()

