from __future__ import annotations
import os, time
from typing import Tuple, Optional, Union
from .hmac_sig import compute_signature, build_signing_string, consteq

# optional Redis backend
_r = None
try:
    from utils.redis_client import get_redis_client  # your project helper (optional)
    _r = get_redis_client()
except Exception:
    _r = None

# in-memory fallback for nonces (PID-local). Best effort only.
_NONCES = {}  # type: ignore[var-annotated]

def _now() -> int:
    return int(time.time())

def _nonce_seen(nonce: str, ttl: int) -> bool:
    ts = _now()
    if _r:
        key = f"anti_replay:nonce:{nonce}"
        try:
            if _r.setnx(key, ts):
                _r.expire(key, ttl)
                return False
            return True
        except Exception:
            pass
    # memory fallback
    try:
        # cleanup sometimes
        if len(_NONCES) > 10000:
            cutoff = ts - ttl
            for k, v in list(_NONCES.items())[:3000]:
                if v < cutoff:
                    _NONCES.pop(k, None)
        if nonce in _NONCES:
            return True
        _NONCES[nonce] = ts
        return False
    except Exception:
        # if memory fails, play safe: treat as seen to avoid replay risk
        return True

def verify_request(
    ts_header: Optional[str],
    nonce_header: Optional[str],
    signature_header: Optional[str],
    route: str,
    body: Union[str, bytes, None],
    require_signature: bool = False,
) -> Tuple[bool, str]:
    """
    Verify anti-replay and HMAC signature.
    Environment:
      ANTI_REPLAY_ENABLE=1/0
      ANTI_REPLAY_REQUIRE_SIGNATURE=1/0
      SIG_TS_ENFORCE=1/0
      SIG_TS_SKEW_SEC=900
      ANTI_REPLAY_NONCE_TTL_SEC=180
      API_SIGNING_SECRET=...
      SIG_ALG=sha256|sha512 (default sha256)
    """
    are = (os.getenv("ANTI_REPLAY_ENABLE", "1").lower() in ("1","true","yes","on"))
    if not are and not require_signature:
        return True, "anti-replay disabled"

    req_sig = (os.getenv("ANTI_REPLAY_REQUIRE_SIGNATURE", "1").lower() in ("1","true","yes","on")) or require_signature
    ts_enf  = (os.getenv("SIG_TS_ENFORCE", "1").lower() in ("1","true","yes","on"))
    skew    = int(os.getenv("SIG_TS_SKEW_SEC", "900") or "900")
    ttl     = int(os.getenv("ANTI_REPLAY_NONCE_TTL_SEC", "180") or "180")
    secret  = os.getenv("API_SIGNING_SECRET", "") or os.getenv("OPS_SIGN_SECRET", "")
    alg     = os.getenv("SIG_ALG", "sha256")

    if req_sig and (not signature_header):
        return False, "missing-signature"
    if ts_enf:
        try:
            ts = int(ts_header or "0")
        except Exception:
            return False, "bad-timestamp"
        now = _now()
        if abs(now - ts) > max(0, skew):
            return False, "stale-timestamp"
    else:
        ts = int(ts_header or _now())

    nonce = (nonce_header or "").strip()
    if not nonce:
        return False, "missing-nonce"
    if _nonce_seen(nonce, ttl):
        return False, "replay-nonce"

    if not req_sig:
        return True, "ok"

    if not secret:
        return False, "missing-secret"

    msg = build_signing_string(
        method = route.split(" ", 1)[0] if " " in route else "GET",
        path_qs = route.split(" ", 1)[1] if " " in route else route,
        body = body or b"",
        ts = ts,
        nonce = nonce,
    )
    sig = compute_signature(secret, msg, alg=alg)
    ok  = consteq(signature_header or "", sig)
    return (True, "ok") if ok else (False, "bad-signature")
