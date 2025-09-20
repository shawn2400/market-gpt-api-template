# utils/idempotency.py
from __future__ import annotations

import os, time, threading, hashlib
from typing import Optional

# ========= Env / Config =========
_REDIS_URL = os.getenv("REDIS_URL", "").strip()
_TTL_DEFAULT = int(os.getenv("IDEMPOTENCY_DEFAULT_TTL_SEC", "120"))
_NS = os.getenv("IDEMPOTENCY_NAMESPACE", "").strip()  # אופציונלי: שם מרחב
_PREFIX = os.getenv("IDEMPOTENCY_PREFIX", "idp").strip() or "idp"
_MAX_KEYS = int(os.getenv("IDEMPOTENCY_MAX_KEYS", "5000"))  # לזיכרון בלבד

# ========= State =========
_store: dict[str, float] = {}
_lock = threading.Lock()

_redis = None
if _REDIS_URL:
    try:
        import redis  # type: ignore
        _redis = redis.from_url(
            _REDIS_URL,
            decode_responses=True,
            socket_timeout=3.0,
            retry_on_timeout=True,
        )
    except Exception:
        _redis = None

# ========= Helpers =========
def _normalize_key(key: str) -> str:
    """
    נורמליזציה קשיחה של המפתח למניעת בעיות תווים/אורך:
    - סטריפ
    - אם ארוך/חריג → SHA256Hex
    - הוספת namespace/prefix
    """
    k = (key or "").strip()
    if not k:
        # מפתח ריק – נטפל בזה בשכבה הקוראת (כאן פשוט נחזיר placeholder)
        k = "empty"
    # אם ארוך/מכיל רווחים/תווים חריגים – נחסום באמצעות hash:
    if len(k) > 120 or any(ch.isspace() for ch in k):
        k = hashlib.sha256(k.encode("utf-8")).hexdigest()
    ns = f"{_NS}:" if _NS else ""
    return f"{_PREFIX}:{ns}{k}"

def _gc_expired(now: float) -> None:
    """ניקוי רשומות שפגו תוקפן בזיכרון; שומר על גודל מפה סביר."""
    # מחיקה לפי תוקף
    rm = [k for k, exp in _store.items() if exp < now]
    for k in rm:
        _store.pop(k, None)
    # הגבלת גודל (אופציונלי)
    if len(_store) > _MAX_KEYS:
        # נמחק את הוותיקים יחסית: נמיין לפי exp (עולה) ונחתוך
        for k, _ in sorted(_store.items(), key=lambda kv: kv[1])[: len(_store) - _MAX_KEYS]:
            _store.pop(k, None)

# ========= Public API =========
def claim(key: str, ttl_sec: Optional[int] = None) -> bool:
    """
    ניסיון "תפיסה" של מפתח idempotency.
    מחזיר:
      True  → נתפס עכשיו (טרי/חדש)
      False → כבר קיים/נראה לאחרונה (כפילות)

    התנהגות:
    - אם יש Redis → נשתמש SET NX EX (אטומי).
    - אחרת, נסמוך על זיכרון מקומי עם נעילה וניקוי אוטומטי.
    """
    ttl = int(ttl_sec or _TTL_DEFAULT)
    if ttl <= 0:
        ttl = _TTL_DEFAULT

    skey = _normalize_key(key)

    # Redis path (עדיף לפרודקשן/ריבוי רפליקות)
    if _redis:
        try:
            # set nx ex = אטומי: יחזיר True אם נוצרה הרשומה (חדש), אחרת False.
            return bool(_redis.set(name=skey, value="1", nx=True, ex=ttl))
        except Exception:
            # אם Redis לא זמין רגעית – ניפול חזרה לזיכרון
            pass

    # In-memory fallback (תהליכון בודד/Pod יחיד)
    now = time.monotonic()
    with _lock:
        _gc_expired(now)
        exp = _store.get(skey)
        if exp and exp > now:
            return False  # כבר נתפס ועדיין בתוקף
        _store[skey] = now + ttl
        return True

def clear(key: str) -> None:
    """
    ניקוי מפורש של המפתח (לא חובה בשימוש רגיל כי TTL מנקה).
    """
    skey = _normalize_key(key)
    if _redis:
        try:
            _redis.delete(skey)
            return
        except Exception:
            pass
    with _lock:
        _store.pop(skey, None)

__all__ = ["claim", "clear"]


