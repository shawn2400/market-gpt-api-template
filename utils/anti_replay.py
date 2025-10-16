# utils/anti_replay.py
from __future__ import annotations
import os, time, hmac, hashlib
from contextlib import suppress
from typing import Optional, Tuple, Any, Dict

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

_NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
_REDIS_URL = os.getenv("REDIS_URL", "").strip()

_SKEW_SEC = int(os.getenv("ANTI_REPLAY_SKEW_SEC", "30") or 30)
_NONCE_TTL = int(os.getenv("ANTI_REPLAY_NONCE_TTL", "45") or 45)
_REQUIRE = os.getenv("ANTI_REPLAY_REQUIRE_SIGNATURE", "1").lower() in ("1","true","yes","on")

# מפתח חתימה: OPS_SIGN_SECRET או WEBHOOK_HMAC_SECRET
_SECRET = (os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET") or "").strip()

async def _get_redis():
    if not (_REDIS_URL and aioredis):
        return None
    r = getattr(_get_redis, "_r", None)
    if r: return r
    r = aioredis.from_url(_REDIS_URL, decode_responses=True)
    _get_redis._r = r  # type: ignore[attr-defined]
    return r

def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def _sign(payload: str) -> str:
    key = _SECRET.encode("utf-8")
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

async def _claim_nonce(nonce: str) -> bool:
    # Redis אם יש; אחרת in-memory קצר
    if _REDIS_URL and aioredis:
        r = await _get_redis()
        if r:
            k = f"{_NS}:nonce:{nonce}"
            ok = await r.setnx(k, "1")
            if ok:
                with suppress(Exception):
                    await r.expire(k, _NONCE_TTL)
            return bool(ok)
    # fallback in-memory
    store: Dict[str, float] = getattr(_claim_nonce, "_mem", {})
    now = time.time()
    # clean
    for k, ts in list(store.items()):
        if now - ts > _NONCE_TTL: store.pop(k, None)
    if nonce in store:
        return False
    store[nonce] = now
    _claim_nonce._mem = store  # type: ignore[attr-defined]
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
    - ts: שניות UNIX (טולרנס _SKEW_SEC)
    - nonce: חד-פעמי, TTL = _NONCE_TTL
    - signature: hex(HMAC_SHA256(secret, f"{ts}|{nonce}|{route}|{sha256(body)}"))
    """
    if not _SECRET:
        return (not (_REQUIRE or require_signature), "no_secret_configured")
    if not (ts_header and nonce_header and signature_header):
        return (not (_REQUIRE or require_signature), "missing_headers")
    try:
        ts = int(ts_header)
    except Exception:
        return (False, "bad_ts")
    now = int(time.time())
    if abs(now - ts) > _SKEW_SEC:
        return (False, "ts_skew")
    if not await _claim_nonce(str(nonce_header)):
        return (False, "nonce_reuse")
    try:
        raw = body if isinstance(body, (bytes, bytearray)) else (str(body).encode("utf-8") if body is not None else b"")
        body_hash = _sha256_hex(raw)
        payload = f"{ts}|{nonce_header}|{route}|{body_hash}"
        expected = _sign(payload)
        ok = hmac.compare_digest(expected, signature_header)
        return (ok, "ok" if ok else "sig_mismatch")
    except Exception as e:
        return (False, f"verify_error:{e}")



