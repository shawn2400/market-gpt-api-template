# utils/anti_replay.py
from __future__ import annotations
import os, time, hmac, hashlib, json
from contextlib import suppress
from typing import Optional, Tuple, Any, Dict

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

_NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
_REDIS_URL = os.getenv("REDIS_URL", "").strip()

# Feature switch
_ENABLED = os.getenv("ANTI_REPLAY_ENABLE", "1").lower() in ("1", "true", "yes", "on")

_SKEW_SEC = int(os.getenv("ANTI_REPLAY_SKEW_SEC", "30") or 30)
_NONCE_TTL = int(os.getenv("ANTI_REPLAY_NONCE_TTL", "45") or 45)
_REQUIRE = os.getenv("ANTI_REPLAY_REQUIRE_SIGNATURE", "1").lower() in ("1","true","yes","on")

# מפתח חתימה: OPS_SIGN_SECRET או WEBHOOK_HMAC_SECRET
_SECRET = (os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET") or "").strip()

async def _get_redis():
    if not (_REDIS_URL and aioredis):
        return None
    r = getattr(_get_redis, "_r", None)
    if r:
        return r
    r = aioredis.from_url(_REDIS_URL, decode_responses=True)
    _get_redis._r = r  # type: ignore[attr-defined]
    return r

def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def _sign(payload: str) -> str:
    key = _SECRET.encode("utf-8")
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

def _norm_body(body: Any) -> bytes:
    """
    נרמול גוף הבקשה לחתימה:
    - bytes: כמו שהוא
    - dict/list: JSON יציב (sort_keys, separators)
    - str: encode utf-8
    - אחר: str() ואז encode utf-8
    """
    if body is None:
        return b""
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    if isinstance(body, (dict, list, tuple)):
        with suppress(Exception):
            return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if isinstance(body, str):
        return body.encode("utf-8")
    return str(body).encode("utf-8")

# in-memory nonce store fallback
_MEM_NONCES: Dict[str, float] = {}

async def _claim_nonce(nonce: str) -> bool:
    # Redis אם יש; אחרת in-memory קצר
    if _REDIS_URL and aioredis:
        with suppress(Exception):
            r = await _get_redis()
            if r:
                k = f"{_NS}:nonce:{nonce}"
                ok = await r.setnx(k, "1")
                if ok:
                    with suppress(Exception):
                        await r.expire(k, _NONCE_TTL)
                return bool(ok)
    # fallback in-memory
    now = time.time()
    # clean
    for k, ts in list(_MEM_NONCES.items()):
        if now - ts > _NONCE_TTL:
            _MEM_NONCES.pop(k, None)
    if nonce in _MEM_NONCES:
        return False
    _MEM_NONCES[nonce] = now
    return True

async def verify_request(
    ts_header: Optional[str],
    nonce_header: Optional[str],
    signature_header: Optional[str],
    route: str,
    body: Any,
    require_signature: bool = False
) -> Tuple[bool, str]:
    """
    אימות חתימה אנטי-ריפליי:
    signature = hex(HMAC_SHA256(secret, f"{ts}|{nonce}|{route}|{sha256(body)}"))
    תנאים:
      - |now - ts| <= _SKEW_SEC
      - nonce חד-פעמי עם TTL
      - אם _REQUIRE או require_signature=True → מחייב כותרות מלאות וחתימה תקפה
    התנהגות:
      - אם ANTI_REPLAY_ENABLE=0 → תמיד OK (לוג בלבד)
      - אם אין SECRET מוגדר → OK רק אם לא חייבים חתימה
    """
    if not _ENABLED:
        return (True, "anti_replay_disabled")

    must = _REQUIRE or bool(require_signature)

    if not _SECRET:
        return (not must, "no_secret_configured")

    if not (ts_header and nonce_header and signature_header):
        return (not must, "missing_headers")

    # timestamp
    try:
        ts = int(ts_header)
    except Exception:
        return (False, "bad_ts")
    now = int(time.time())
    if abs(now - ts) > _SKEW_SEC:
        return (False, "ts_skew")

    # nonce (single-use)
    if not await _claim_nonce(str(nonce_header)):
        return (False, "nonce_reuse")

    # body hash + signature
    try:
        body_bytes = _norm_body(body)
        body_hash = _sha256_hex(body_bytes)
        payload = f"{ts}|{nonce_header}|{route}|{body_hash}"
        expected = _sign(payload)
        sig = signature_header.strip()
        ok = hmac.compare_digest(expected, sig)
        return (ok or (not must), "ok" if ok else "sig_mismatch")
    except Exception as e:
        return (False, f"verify_error:{e}")




