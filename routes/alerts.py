# routes/alerts.py
from __future__ import annotations
import os, json, logging, binascii, hmac, hashlib
from typing import Any, Dict, Optional
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

# Bearer (רשותי כש-HMAC כבוי)
from security.hmac_verify import verify_bearer  # משמש רק כגיבוי כש-HMAC לא חובה

# idem + rate limit נשארים כפי שהם אצלך
from utils.idempotency import idem_for_request, DEFAULT_TTL_SEC
from utils.rate_limit import allow as rl_allow

# storage (רשותי)
try:
    from utils.storage import save_payload
except Exception:
    def save_payload(obj: Dict[str, Any], *, expire: int = 600) -> str:  # type: ignore
        # Shim: לא שומר פיזית, רק מחזיר "about:blank"
        return "about:blank"

log = logging.getLogger("algogpt.alerts")

router = APIRouter(prefix="/alerts", tags=["Alerts"])

# מדיניות ENV
HMAC_REQUIRED = (os.getenv("ALERTS_HMAC_REQUIRED", "1").lower() in ("1", "true", "yes", "on"))
IDEM_TTL_SEC  = int(os.getenv("ALERTS_IDEMPOTENCY_TTL_SEC", str(DEFAULT_TTL_SEC)))
RL_LIMIT      = int(os.getenv("ALERTS_RL_LIMIT", "60"))
RL_WINDOW     = int(os.getenv("ALERTS_RL_WINDOW", "60"))

# ========= HMAC helpers (מקבלים כמה פורמטים נפוצים) =========
def _get_secret_bytes() -> Optional[bytes]:
    """
    סדר עדיפויות: ALERTS_INGEST_HMAC_SECRET -> WEBHOOK_HMAC_SECRET -> OPS_SIGN_SECRET
    אם ALERTS_INGEST_HMAC_KEY_IS_HEX=1 — נפרש HEX; אחרת ASCII bytes.
    """
    s = (
        os.getenv("ALERTS_INGEST_HMAC_SECRET")
        or os.getenv("WEBHOOK_HMAC_SECRET")
        or os.getenv("OPS_SIGN_SECRET")
    )
    if not s:
        return None
    if os.getenv("ALERTS_INGEST_HMAC_KEY_IS_HEX", "0") in ("1", "true", "yes", "on"):
        try:
            return binascii.unhexlify(s)
        except Exception:
            # אם HEX לא חוקי — ניפול ל־ASCII
            return s.encode()
    return s.encode()

def _hmac_hex(k: bytes, msg: bytes) -> str:
    return hmac.new(k, msg, hashlib.sha256).hexdigest()

def _hmac_b64(k: bytes, msg: bytes) -> str:
    import base64
    return base64.b64encode(hmac.new(k, msg, hashlib.sha256).digest()).decode()

async def verify_ingest_hmac(request: Request) -> None:
    """
    מאמת חתימה על RAW body במספר פורמטים:
    1) X-Webhook-Hmac / X-Signature = HEX(sha256(key, RAW))
    2) X-Webhook-Hmac / X-Signature = Base64(sha256(key, RAW))
    3) X-Hub-Signature-256 = 'sha256=' + HEX(sha256(key, RAW))  (פורמט GitHub)
    4) תמיכה אופציונלית ב-TS: msg = f"{ts}." + RAW
    """
    body = await request.body()
    # כותרות נפוצות
    got = request.headers.get("X-Webhook-Hmac", "") or request.headers.get("X-Signature", "")
    hub = request.headers.get("X-Hub-Signature-256", "")  # "sha256=<hex>"
    ts  = request.headers.get("X-Webhook-Ts", "")

    key = _get_secret_bytes()
    if not key:
        raise HTTPException(status_code=500, detail="HMAC secret not configured")

    # 1) RAW→HEX (ברירת המחדל כמו /_debug/hmac)
    if got and got == _hmac_hex(key, body):
        return

    # 2) RAW→Base64
    if got and got == _hmac_b64(key, body):
        return

    # 3) GitHub style: sha256=<hex>
    if hub and hub.startswith("sha256=") and hub[7:] == _hmac_hex(key, body):
        return

    # 4) תמיכה ב־timestamp prefix: f"{ts}." + RAW
    if ts:
        msg = (ts + ".").encode() + body
        if got and got == _hmac_hex(key, msg):
            return
        if hub and hub.startswith("sha256=") and hub[7:] == _hmac_hex(key, msg):
            return
        if got and got == _hmac_b64(key, msg):
            return

    # כישלון — לא לחשוף פרטים
    raise HTTPException(status_code=401, detail="Invalid HMAC signature")

# ========= Schemas =========
class IngestResponse(BaseModel):
    ok: bool = True
    accepted: bool = True
    dedup: bool = False
    stored_url: Optional[str] = None
    reason: Optional[str] = None

# ========= Handlers =========
@router.post("/ingest", response_model=IngestResponse, summary="Ingest trading alerts (TradingView / custom)")
async def ingest_alert(request: Request) -> IngestResponse:
    # ── Rate limit per IP ──
    ip = request.client.host if request.client else "unknown"
    allowed, remaining = await rl_allow("alerts", ip, limit=RL_LIMIT, window_sec=RL_WINDOW)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # ── Auth/HMAC ──
    if HMAC_REQUIRED:
        # קו אחיד: אימות לפי ה־RAW כמו הדיבאגר + תמיכה בפורמטים נוספים
        await verify_ingest_hmac(request)
    else:
        # אם HMAC לא חובה – ננסה Bearer; אם גם הוא לא קיים, נאפשר (development) רק אם ALLOW_ALERTS_WITHOUT_AUTH=1
        if not verify_bearer(request):
            if os.getenv("ALLOW_ALERTS_WITHOUT_AUTH", "0").lower() not in ("1", "true", "yes", "on"):
                raise HTTPException(status_code=401, detail="Unauthorized")

    # ── Body ── (ללא קנוניקליזציה! חותמים על RAW)
    raw = await request.body()
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            payload = {"raw": payload}
    except Exception:
        payload = {"raw": raw.decode("utf-8", "ignore")}

    # ── Idempotency ──
    headers_lower = {k: v for k, v in request.headers.items()}
    fresh = await idem_for_request(raw, headers_lower, extra={"path": str(request.url.path)}, ttl_sec=IDEM_TTL_SEC)
    if not fresh:
        # כפילות – לא נעבד שוב
        return IngestResponse(ok=True, accepted=False, dedup=True, reason="duplicate")

    # ── Persist (קליל) ──
    url = None
    try:
        url = save_payload({"kind": "alert", "ip": ip, "payload": payload}, expire=600)
    except Exception as e:
        log.warning("alerts.save_payload_failed: %s", e)

    # כאן אפשר לשרשר למעבד פנימי/תור (רשותי)
    # try:
    #     await internal_queue.put(payload)
    # except Exception:
    #     pass

    return IngestResponse(ok=True, accepted=True, stored_url=url)

# Ping קטן
@router.get("/ping")
async def ping_alerts() -> Dict[str, Any]:
    return {
        "ok": True,
        "hmac_required": HMAC_REQUIRED,
        "rl": {"limit": RL_LIMIT, "window": RL_WINDOW},
    }




















