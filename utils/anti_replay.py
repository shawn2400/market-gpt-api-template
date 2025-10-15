# utils/anti_replay.py
from __future__ import annotations

import os
import hmac
import json
import time
import hashlib
import logging
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger("algogpt.anti_replay")

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
ANTI_REPLAY_ENABLE = os.getenv("ANTI_REPLAY_ENABLE", "1").lower() in ("1", "true", "yes", "on")
WINDOW_SEC = int(os.getenv("ANTI_REPLAY_WINDOW_SEC", "60"))
SIGNING_SECRET = (os.getenv("API_SIGNING_SECRET") or "").encode("utf-8")

REDIS_URL = os.getenv("REDIS_URL") or os.getenv("CACHE_URL") or ""
_USE_REDIS = bool(REDIS_URL)

# -----------------------------------------------------------------------------
# Storage (Redis/non-Redis fallback)
# -----------------------------------------------------------------------------
_redis = None
_mem_seen: Dict[str, float] = {}

def _get_redis():
    global _redis
    if _redis or not _USE_REDIS:
        return _redis
    try:
        import redis  # type: ignore
        _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        # Sanity
        _redis.ping()
        return _redis
    except Exception as e:
        logger.warning("anti_replay: redis unavailable (%s) — falling back to in-proc memory", e)
        return None

def _seen_add(key: str, ttl: int) -> bool:
    """
    returns True if key was added (i.e., not seen before), False if replay.
    """
    r = _get_redis()
    now = time.time()
    if r:
        try:
            # SET key NX EX ttl
            ok = r.set(name=f"nonce:{key}", value=str(int(now)), nx=True, ex=int(ttl))
            return bool(ok)
        except Exception:
            pass
    # Fallback: in-proc memory
    # purge stale
    dead = []
    for k, ts in _mem_seen.items():
        if now - ts > ttl:
            dead.append(k)
    for k in dead:
        _mem_seen.pop(k, None)
    if key in _mem_seen:
        return False
    _mem_seen[key] = now
    return True

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _canon_body(body: Any) -> str:
    """
    Build canonical JSON for signing: stable key order, no spaces.
    If body is bytes/str — use as-is (sha256 of raw).
    """
    try:
        if body is None:
            return ""
        if isinstance(body, (bytes, bytearray)):
            # interpret as utf-8 json if possible, else raw
            try:
                obj = json.loads(body.decode("utf-8"))
                return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
            except Exception:
                return body.decode("utf-8", errors="ignore")
        if isinstance(body, str):
            try:
                obj = json.loads(body)
                return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
            except Exception:
                return body
        # dict/list/…
        return json.dumps(body, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    except Exception:
        return ""

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _build_sign_base(ts: str, nonce: str, route: str, canon_json: str) -> str:
    return f"{ts}.{nonce}.{route}.{_sha256(canon_json)}"

def _hmac(base: str, secret: bytes) -> str:
    return hmac.new(secret, base.encode("utf-8"), hashlib.sha256).hexdigest()

# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
class AntiReplayError(Exception):
    def __init__(self, code: str, detail: Optional[str] = None):
        self.code = code
        self.detail = detail or code
        super().__init__(f"{code}: {detail}")

def verify_request(
    *,
    ts_header: Optional[str],
    nonce_header: Optional[str],
    signature_header: Optional[str],
    route: str,
    body: Any,
    require_signature: bool = False,
    window_sec: Optional[int] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Verify (timestamp, nonce, optional HMAC) and store nonce.
    Returns (ok, reason_if_not_ok).
    """
    if not ANTI_REPLAY_ENABLE:
        return True, None

    try:
        if not ts_header or not nonce_header:
            return False, "missing_ts_or_nonce"

        window = int(window_sec or WINDOW_SEC)
        ts = int(str(ts_header).strip())
        now = int(time.time())
        if abs(now - ts) > window:
            return False, "timestamp_out_of_window"

        # Nonce uniqueness (per window)
        # Key includes route and ts to improve uniqueness while still catching replays
        uniq = f"{route}:{ts}:{nonce_header.strip()}"
        if not _seen_add(uniq, ttl=window):
            return False, "replay_detected"

        # Signature (optional but recommended)
        if SIGNING_SECRET:
            canon = _canon_body(body)
            base = _build_sign_base(str(ts), nonce_header.strip(), route, canon)
            calc = _hmac(base, SIGNING_SECRET)
            if not signature_header:
                if require_signature:
                    return False, "signature_required"
                else:
                    # soft-pass: allow, but warn
                    logger.warning("anti_replay: signature missing; route=%s", route)
            else:
                got = str(signature_header).strip().lower()
                if got != calc.lower():
                    return False, "bad_signature"

        return True, None
    except Exception as e:
        logger.warning("anti_replay: verify error: %s", e)
        return False, "verify_exception"

def build_signature_headers(route: str, body: Any) -> Dict[str, str]:
    """
    Utility for internal callers that POST to our own endpoints.
    """
    ts = str(int(time.time()))
    nonce = hashlib.sha256(f"{ts}.{os.getpid()}.{time.time()}".encode()).hexdigest()[:16]
    canon = _canon_body(body)
    base = _build_sign_base(ts, nonce, route, canon)
    sig = _hmac(base, SIGNING_SECRET) if SIGNING_SECRET else ""
    h = {
        "X-Timestamp": ts,
        "X-Nonce": nonce,
    }
    if sig:
        h["X-Signature"] = sig
    return h


