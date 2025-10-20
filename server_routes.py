# server_routes.py
from __future__ import annotations
import json
import os
import time
import hmac
import hashlib
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Depends, Query, Header
from pydantic import BaseModel
import httpx
import redis

from server_signing import verify_signature

app = FastAPI(title="Signed Approvals Sidecar")

# -------- ENV --------
# חובה שה־NS ו־REDIS_URL יתאימו לשירות הראשי כדי למשוך את הטיקט שנוצר שם
NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web:staging").strip() or "ops-supervisor-web:staging"
REDIS_URL = os.getenv("REDIS_URL", "").strip()

# כתובת ההרצה בשירות הראשי (endpoint פנימי שמבצע הזמנה בפועל)
# מומלץ לכוון אל https://algogpt-staging.onrender.com/ops/approve/signed
EXECUTE_URL = os.getenv("EXECUTE_URL", "").strip()

# Bearer (אל השירות הראשי) + חתימת HMAC על גוף ה־JSON
EXECUTE_BEARER = os.getenv("API_BEARER_TOKEN", "").strip()
WEBHOOK_HMAC_SECRET = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()

# הגנת Bearer על השירות SIDE-CAR הזה (אופציונלי)
REQUIRE_BEARER = (os.getenv("REQUIRE_BEARER", "0").lower() in {"1", "true", "yes", "on"})
API_BEARER_TOKEN_SELF = os.getenv("API_BEARER_TOKEN_SELF", os.getenv("API_BEARER_TOKEN", "")).strip()

# -------- Clients --------
_r: Optional[redis.Redis] = None
_http: Optional[httpx.Client] = None

# -------- Models --------
class ApproveResponse(BaseModel):
    ok: bool
    ticket_id: str
    detail: str | None = None
    executed: Any | None = None

class HealthResponse(BaseModel):
    ok: bool
    redis: bool
    require_bearer: bool
    execute_url: str | None = None
    namespace: str

# -------- Helpers --------
def _clean_redis_url(u: str) -> str:
    """תיקון REDIS_URL בסגנון Render, כולל rediss:// ופסילות תווים."""
    if not u:
        return u
    u = u.strip().strip('"').strip("'").strip()
    u = u.replace("\\n", "").rstrip("\n")
    if u.startswith("//") and "keyvalue.render.com" in u:
        u = "rediss:" + u
    if "keyvalue.render.com" in u and not u.startswith("redis://") and not u.startswith("rediss://"):
        u = "rediss://" + u.split("://", 1)[-1]
    return u

def _tkey(ticket_id: str) -> str:
    return f"{NS}:ticket:{ticket_id}"

def _sign_hex(secret_hex_or_text: str, payload: bytes) -> str:
    key = bytes.fromhex(secret_hex_or_text) if len(secret_hex_or_text) == 64 else secret_hex_or_text.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

def _load_ticket(ticket_id: str) -> Optional[Dict[str, Any]]:
    """
    מושך את הטיקט מ־Redis של השירות הראשי (אותו NS).
    create_ticket הראשי שומר אובייקט: {"ts": ..., "req": {...}, "note": "..."}
    אנו צריכים את req (הטיקט המלא).
    """
    if not _r:
        return None
    raw = _r.get(_tkey(ticket_id))
    if not raw:
        return None
    try:
        rec = json.loads(raw)
        # תמיכה גם במבנה ישן/אחר — ננסה "req" ואם אין, נחזיר את כולו
        return rec.get("req") or rec
    except Exception:
        return None

def require_bearer(authorization: str | None = Header(default=None)) -> bool:
    if not REQUIRE_BEARER:
        return True
    if not API_BEARER_TOKEN_SELF:
        raise HTTPException(status_code=500, detail="Bearer required but API_BEARER_TOKEN_SELF not set")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    if token != API_BEARER_TOKEN_SELF:
        raise HTTPException(status_code=403, detail="Invalid bearer token")
    return True

# -------- Lifecycle --------
@app.on_event("startup")
def _startup():
    global _r, _http
    if not REDIS_URL:
        raise RuntimeError("REDIS_URL is required")
    _r = redis.Redis.from_url(_clean_redis_url(REDIS_URL), decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
    try:
        _r.ping()
    except Exception as e:
        raise RuntimeError(f"Redis ping failed: {e}")
    _http = httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0))

@app.on_event("shutdown")
def _shutdown():
    global _http
    try:
        if _http:
            _http.close()
    finally:
        _http = None

# -------- Routes --------
@app.get("/health", response_model=HealthResponse)
def health():
    ok = False
    try:
        ok = bool(_r and _r.ping())
    except Exception:
        ok = False
    return HealthResponse(
        ok=ok,
        redis=ok,
        require_bearer=REQUIRE_BEARER,
        execute_url=EXECUTE_URL or None,
        namespace=NS,
    )

@app.get("/ops/approve/signed", response_model=ApproveResponse)
def approve_signed(
    ticket_id: str = Query(..., description="Ticket id"),
    exp: str = Query(..., description="Expiry (unix seconds or ms)"),
    sig: str = Query(..., description="HMAC-SHA256 signature (hex or b64url)"),
    _auth_ok: bool = Depends(require_bearer),
):
    # 1) אימות פרמטרים חתומים ב־URL
    ok, why = verify_signature(ticket_id, exp, sig)
    if not ok:
        raise HTTPException(status_code=401, detail=f"Bad signature: {why}")

    # 2) שליפת הטיקט המלא מ־Redis של השירות הראשי
    ticket = _load_ticket(ticket_id)
    if not ticket:
        # פידבק ברור — הצד הראשי יוצר את הטיקט ושומר ב־Redis; אם לא נמצא, אין מה לבצע.
        raise HTTPException(status_code=404, detail="ticket not found (sidecar couldn't load from Redis)")

    # 3) קריאה לשירות הראשי /ops/approve/signed (POST עם JSON מלא + חתימה על הגוף)
    if not EXECUTE_URL:
        raise HTTPException(status_code=500, detail="EXECUTE_URL not set")

    body = json.dumps(ticket, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if EXECUTE_BEARER:
        headers["Authorization"] = f"Bearer {EXECUTE_BEARER}"
    if WEBHOOK_HMAC_SECRET:
        headers["X-Signature"] = _sign_hex(WEBHOOK_HMAC_SECRET, body)

    try:
        assert _http is not None
        r = _http.post(EEXECUTE_URL if (EEXECUTE_URL := os.getenv("EEXECUTE_URL","")) else EXECUTE_URL, content=body, headers=headers)
        # ^ מאפשר override חירום ע"י EEXECUTE_URL (אם צריך cut-over מיידי)
        if r.status_code >= 300:
            raise HTTPException(status_code=502, detail={"execute_error": r.text, "status": r.status_code})
        try:
            executed = r.json()
        except Exception:
            executed = {"text": r.text, "status": r.status_code}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"execution call failed: {e}")

    # 4) החזרת תשובה ברורה
    return ApproveResponse(ok=True, ticket_id=ticket_id, detail="approved", executed=executed)

