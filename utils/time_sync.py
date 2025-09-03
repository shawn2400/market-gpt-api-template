# utils/time_sync.py
from __future__ import annotations
import os, time, threading, logging
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger("algogpt.time_sync")

# =========================
# ENV / Tunables
# =========================
_BINANCE_BASE = (os.getenv("BINANCE_FUTURES_HTTP_BASE") or "https://fapi.binance.com").rstrip("/")
_HTTP_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
_SYNC_TTL_SEC = int(os.getenv("TIME_SYNC_TTL_SEC", "3600"))   # ברירת מחדל: שעה
# window קבוע לכל חתימה (סעיף 105); בפועל נטליא ע"י binance_client אבל נאפשר כאן חשיפה
_RECV_WINDOW_MS = int(os.getenv("RECV_WINDOW_MS", os.getenv("BINANCE_RECV_WINDOW", "45000")))

# כמה דגימות לכל sync כדי להקטין jitter
_SAMPLES = int(os.getenv("TIME_SYNC_SAMPLES", "3"))
_SAMPLES = max(1, min(_SAMPLES, 5))

# =========================
# State (thread-safe)
# =========================
_lock = threading.Lock()
_offset_ms: int = 0                 # serverTime - local(now)
_last_sync_monotonic: float = 0.0   # מתי סונכרן לאחרונה (monotonic)
_last_server_time_ms: Optional[int] = None

_bg_thread: Optional[threading.Thread] = None
_bg_stop = threading.Event()

# =========================
# Core helpers
# =========================
def _client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(_HTTP_TIMEOUT),
        headers={"Accept": "application/json", "Accept-Encoding": "gzip", "User-Agent": "AlgoGPT/time-sync"},
        http2=False,
    )

def _sample_server_time() -> Optional[int]:
    """דגימת serverTime בודדת מה־/fapi/v1/time. מחזיר ms או None במקרה כשל."""
    url = f"{_BINANCE_BASE}/fapi/v1/time"
    try:
        with _client() as c:
            t0 = time.perf_counter()           # לסטטיסטיקה בלבד
            r = c.get(url)
            t1 = time.perf_counter()
            r.raise_for_status()
            js = r.json()
            st = int(js.get("serverTime"))
            # לוג איטיות חריגה בלבד
            dur_ms = (t1 - t0) * 1000.0
            if dur_ms > 250:
                logger.debug({"event": "time_sync_slow", "latency_ms": round(dur_ms, 1)})
            return st
    except Exception as e:
        logger.warning({"event": "time_sync_sample_failed", "error": str(e)})
        return None

def _best_of_n_server_time() -> Optional[int]:
    """לוקח כמה דגימות ובוחר חציון כדי לצמצם jitter."""
    vals = []
    for _ in range(_SAMPLES):
        st = _sample_server_time()
        if st is not None:
            vals.append(st)
        # שינה זעירה בין דגימות — לא חובה
        if _SAMPLES > 1:
            time.sleep(0.03)
    if not vals:
        return None
    vals.sort()
    return vals[len(vals) // 2]  # median

# =========================
# Public API
# =========================
def sync_now() -> Dict[str, Any]:
    """
    מבצע סנכרון מיידי מול Binance:
      offset_ms = serverTime - localTime(now_ms)
    מעדכן סטייט גלובלי. מחזיר מטא להדפסה/דיבאג.
    """
    st_ms = _best_of_n_server_time()
    if st_ms is None:
        # לא מעדכן offset אם נכשל — נשארים על הערך האחרון
        with _lock:
            return {
                "ok": False,
                "error": "server_time_unavailable",
                "offset_ms": _offset_ms,
                "last_sync_age_sec": (time.monotonic() - _last_sync_monotonic) if _last_sync_monotonic else None,
            }

    now_ms = int(time.time() * 1000)
    with _lock:
        global _offset_ms, _last_sync_monotonic, _last_server_time_ms
        _offset_ms = int(st_ms - now_ms)
        _last_server_time_ms = st_ms
        _last_sync_monotonic = time.monotonic()
        logger.info({"event": "time_sync_ok", "offset_ms": _offset_ms})
        return {"ok": True, "offset_ms": _offset_ms, "server_time_ms": st_ms}

def ensure_fresh_sync(ttl_sec: Optional[int] = None) -> None:
    """
    מבטיח שסנכרון לא פג תוקף. אם עבר TTL — מבצע sync_now().
    שימוש ב־monotonic בהתאם לסעיף 106.
    """
    ttl = int(ttl_sec if ttl_sec is not None else _SYNC_TTL_SEC)
    need = False
    with _lock:
        age = (time.monotonic() - _last_sync_monotonic) if _last_sync_monotonic else 1e9
        need = age >= ttl
    if need:
        sync_now()

def server_time_ms() -> int:
    """
    מחזיר הערכת serverTime נוכחית: local_now_ms + offset_ms.
    אם TTL פג — ירענן תחילה (חד־קריאה ל־/time). 
    """
    ensure_fresh_sync()
    with _lock:
        return int(time.time() * 1000) + int(_offset_ms)

def get_offset_ms() -> int:
    """ה־offset האחרון הידוע (ms). לא מבצע רענון."""
    with _lock:
        return _offset_ms

def recv_window_ms() -> int:
    """חלון חתימה אחיד (ms) לכל קריאות החתימה (סעיף 105)."""
    return int(_RECV_WINDOW_MS)

def last_server_time_ms() -> Optional[int]:
    """הדגימה האחרונה שהוחזרה מ־Binance (אם קיימת)."""
    with _lock:
        return _last_server_time_ms

def monotonic_now() -> float:
    """שעון מונוטוני לשימוש ב־debounce/TTL (סעיף 106)."""
    return time.monotonic()

# =========================
# Background refresher (אופציונלי)
# =========================
def start_background_sync(interval_sec: int | None = None) -> None:
    """
    רענון תקופתי (ברירת מחדל: TTL/2). בטוח להרצה חוזרת.
    לא חובה — אפשר להסתפק ב־ensure_fresh_sync() על דרישה.
    """
    global _bg_thread
    if _bg_thread and _bg_thread.is_alive():
        return
    _bg_stop.clear()
    period = int(interval_sec if interval_sec else max(60, _SYNC_TTL_SEC // 2))

    def _run():
        # סנכרון ראשוני שקט
        try: sync_now()
        except Exception: pass
        while not _bg_stop.is_set():
            # שינה עם jitter זעיר כדי לא "לינעל" על שנייה עגולה
            sleep_for = period + (0.05 if period < 120 else 0.0)
            _bg_stop.wait(timeout=sleep_for)
            if _bg_stop.is_set():
                break
            try:
                sync_now()
            except Exception:
                # לא מפילים ת’רד על כשל סנכרון חד־פעמי
                pass

    t = threading.Thread(target=_run, name="time_sync_bg", daemon=True)
    t.start()
    _bg_thread = t
    logger.info({"event": "time_sync_bg_started", "interval_sec": period})

def stop_background_sync() -> None:
    global _bg_thread
    _bg_stop.set()
    if _bg_thread and _bg_thread.is_alive():
        try:
            _bg_thread.join(timeout=1.0)
        except Exception:
            pass
    _bg_thread = None
    logger.info({"event": "time_sync_bg_stopped"})

# =========================
# Lightweight validator
# =========================
def timestamp_within_recv_window(ts_ms: int) -> bool:
    """
    בודק אם חותמת מקומית (client) צפויה להתקבל בשרת לפי ה־offset הידוע וה־recvWindow.
    שימושי ללוג/דיאגנוסטיקה לפני חתימה.
    """
    st_now = server_time_ms()
    return abs(st_now - int(ts_ms)) <= recv_window_ms()

__all__ = [
    "sync_now",
    "ensure_fresh_sync",
    "server_time_ms",
    "get_offset_ms",
    "recv_window_ms",
    "last_server_time_ms",
    "monotonic_now",
    "start_background_sync",
    "stop_background_sync",
    "timestamp_within_recv_window",
]

