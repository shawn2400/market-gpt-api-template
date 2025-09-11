# routes/provider_cryptopanic.py
from __future__ import annotations
import os, hmac, hashlib, time, json, ipaddress, logging
from typing import Optional, List

from fastapi import APIRouter, Request, HTTPException, Header

# Redis אופציונלי לאידמפוטנציה ו-RL
try:
    import redis as _redis
except Exception:
    _redis = None

# האם להציג את ה-webhook ב-OpenAPI (נשלט מה-ENV, ברירת מחדל = לא)
SHOW_DOCS = os.getenv("SHOW_WEBHOOKS_IN_DOCS", "0").lower() in ("1", "true", "yes", "on")
router = APIRouter(
    prefix="/provider/cryptopanic",
    tags=["Provider", "Webhook"],
    include_in_schema=SHOW_DOCS,
)

# ────────────────────────────────────────────────────────────────────────────────
# ENV
# ────────────────────────────────────────────────────────────────────────────────
def _split_csv(val: str) -> List[str]:
    return [x.strip() for x in val.split(",") if x.strip()]

HMAC_SECRET = (os.getenv("CP_HMAC_SECRET", "")).encode("utf-8")
ALLOWLIST   = _split_csv(os.getenv("CP_IP_ALLOWLIST", ""))  # דוגמה: "1.2.3.4,10.0.0.0/8"
RPM         = int(os.getenv("CP_RPM", "60"))
BURST       = int(os.getenv("CP_BURST", "60"))
IDEMP_TTL   = int(os.getenv("CP_IDEMP_TTL_SEC", "600"))
SKEW        = int(os.getenv("CP_MAX_SKEW_SEC", "180"))

# Redis (אם ניתן)
_redis_cli = None
if _redis:
    try:
        url = os.getenv("REDIS_URL", "")
        if url:
            _redis_cli = _redis.Redis.from_url(url, decode_responses=True)
    except Exception:
        _redis_cli = None

_mem = {"rl": {}, "seen": {}}  # נפילה חזרה לזיכרון אם אין Redis

log = logging.getLogger("algogpt.cryptopanic")


# ────────────────────────────────────────────────────────────────────────────────
# Utilities
# ────────────────────────────────────────────────────────────────────────────────
def _now() -> int:
    return int(time.time())

def _client_ip(request: Request) -> str:
    # מאחורי פרוקסי:
    xf = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if xf:
        return xf.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"

def _ip_allowed(ip: str) -> bool:
    if not ALLOWLIST:
        return True
    try:
        ip_obj = ipaddress.ip_address(ip)
    except Exception:
        return False
    for entry in ALLOWLIST:
        try:
            if "/" in entry:
                if ip_obj in ipaddress.ip_network(entry, strict=False):
                    return True
            else:
                if ip == entry:
                    return True
        except Exception:
            continue
    return False

def _hmac_hex(data: bytes) -> str:
    return hmac.new(HMAC_SECRET, data, hashlib.sha256).hexdigest()

def _secure_eq(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a, b)
    except Exception:
        return a == b

async def _rate_limit(ip: str):
    if not RPM:
        return
    if _redis_cli:
        k = f"cp:rl:{ip}:{_now()//60}"
        cnt = _redis_cli.incr(k)
        if cnt == 1:
            _redis_cli.expire(k, 70)
        if cnt > max(RPM, BURST):
            raise HTTPException(429, "rate limit exceeded")
    else:
        minute_key = (_now()//60, ip)
        bucket = _mem["rl"].get(minute_key, 0) + 1
        _mem["rl"][minute_key] = bucket
        # ניקוי ישן
        for (m, i) in list(_mem["rl"].keys()):
            if m < _now()//60:
                _mem["rl"].pop((m, i), None)
        if bucket > max(RPM, BURST):
            raise HTTPException(429, "rate limit exceeded")

def _idem_check(event_id: str) -> bool:
    """True = חדש; False = כפול"""
    if _redis_cli:
        k = f"cp:idem:{event_id}"
        ok = _redis_cli.set(k, "1", ex=IDEMP_TTL, nx=True)
        return bool(ok)
    # זיכרון מקומי
    now = _now()
    # ניקוי ישן
    for k, ts in list(_mem["seen"].items()):
        if ts < now - IDEMP_TTL:
            _mem["seen"].pop(k, None)
    if event_id in _mem["seen"]:
        return False
    _mem["seen"][event_id] = now
    return True


# ────────────────────────────────────────────────────────────────────────────────
# Routes
# ────────────────────────────────────────────────────────────────────────────────
@router.get("/ping")
async def ping():
    return {"ok": True, "src": "cryptopanic", "ts": _now()}

@router.post("/webhook")
async def webhook(
    request: Request,
    x_cp_signature: Optional[str] = Header(default=None, convert_underscores=False),
    x_cryptopanic_signature: Optional[str] = Header(default=None, convert_underscores=False),
    x_cp_timestamp: Optional[str] = Header(default=None, convert_underscores=False),
    x_event_id: Optional[str] = Header(default=None, convert_underscores=False),
):
    if not HMAC_SECRET:
        raise HTTPException(500, "HMAC secret not configured")

    ip = _client_ip(request)
    if not _ip_allowed(ip):
        raise HTTPException(403, "ip not allowed")

    await _rate_limit(ip)

    raw = await request.body()

    # אימות חתימה
    provided = (x_cp_signature or x_cryptopanic_signature or "").strip().lower()
    if not provided:
        raise HTTPException(401, "missing signature")

    # A) חותמים גוף RAW
    expected_a = _hmac_hex(raw)

    # B) חותמים "<timestamp>.<body>"
    expected_b = None
    if x_cp_timestamp:
        expected_b = _hmac_hex((x_cp_timestamp.strip() + ".").encode("utf-8") + raw)

    if not (_secure_eq(provided, expected_a) or (expected_b and _secure_eq(provided, expected_b))):
        raise HTTPException(401, "bad signature")

    # JSON
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "invalid json")

    # בדיקת skew לפי כותרת או שדה ts בגוף
    ts = None
    if x_cp_timestamp and x_cp_timestamp.isdigit():
        ts = int(x_cp_timestamp)
    elif isinstance(payload, dict) and isinstance(payload.get("ts"), (int, float)):
        ts = int(payload["ts"])
    if ts is not None and SKEW > 0 and abs(_now() - ts) > SKEW:
        raise HTTPException(400, "timestamp skew too large")

    # אידמפוטנציה
    body_hash = hashlib.sha256(raw).hexdigest()
    event_id = x_event_id or str(payload.get("id") or body_hash)
    if not _idem_check(event_id):
        return {"ok": True, "duplicate": True, "event_id": event_id}

    # כאן תוכל לבצע את הלוגיקה העסקית שלך (דחיפה לתור, אנליזה, פתיחת טרייד, לוג וכו')
    log.info("cryptopanic_event", extra={"event_id": event_id, "ip": ip, "payload": payload})

    return {"ok": True, "accepted": True, "event_id": event_id}


