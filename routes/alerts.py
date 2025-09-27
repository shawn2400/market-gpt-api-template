# routes/alerts.py
from __future__ import annotations
import os, json, logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from security.hmac_verify import verify_request_hmac, verify_bearer
from utils.idempotency import idem_for_request, DEFAULT_TTL_SEC
from utils.rate_limit import allow as rl_allow

try:
    from utils.storage import save_payload
except Exception:
    def save_payload(obj: Dict[str, Any], *, expire: int = 600) -> str:  # type: ignore
        return "about:blank"

log = logging.getLogger("algogpt.alerts")
router = APIRouter(prefix="/alerts", tags=["Alerts"])

HMAC_REQUIRED = (os.getenv("ALERTS_HMAC_REQUIRED", "1").lower() in ("1", "true", "yes", "on"))
IDEM_TTL_SEC  = int(os.getenv("ALERTS_IDEMPOTENCY_TTL_SEC", str(DEFAULT_TTL_SEC)))
RL_LIMIT      = int(os.getenv("ALERTS_RL_LIMIT", "60"))
RL_WINDOW     = int(os.getenv("ALERTS_RL_WINDOW", "60"))
DEBUG_ALERTS_HMAC_CHECK = (os.getenv("DEBUG_ALERTS_HMAC_CHECK", "0").lower() in ("1","true","yes","on"))

class IngestResponse(BaseModel):
    ok: bool = True
    accepted: bool = True
    dedup: bool = False
    stored_url: Optional[str] = None
    reason: Optional[str] = None

@router.post("/ingest", response_model=IngestResponse, summary="Ingest trading alerts (TradingView / custom)")
async def ingest_alert(request: Request) -> IngestResponse:
    # rate limit
    ip = request.client.host if request.client else "unknown"
    allowed, _remaining = await rl_allow("alerts", ip, limit=RL_LIMIT, window_sec=RL_WINDOW)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # auth
    if HMAC_REQUIRED:
        ok, reason = await verify_request_hmac(request)
        if not ok:
            raise HTTPException(status_code=401, detail=f"Invalid HMAC signature: {reason}")
    else:
        if not verify_bearer(request):
            if os.getenv("ALLOW_ALERTS_WITHOUT_AUTH", "0").lower() not in ("1","true","yes","on"):
                raise HTTPException(status_code=401, detail="Unauthorized")

    # body (בלי קנוניקליזציה – החתימה נעשתה על RAW)
    raw = await request.body()
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            payload = {"raw": payload}
    except Exception:
        payload = {"raw": raw.decode("utf-8", "ignore")}

    # idempotency
    headers_lower = {k: v for k, v in request.headers.items()}
    fresh = await idem_for_request(raw, headers_lower, extra={"path": str(request.url.path)}, ttl_sec=IDEM_TTL_SEC)
    if not fresh:
        return IngestResponse(ok=True, accepted=False, dedup=True, reason="duplicate")

    # persist (קליל)
    url = None
    try:
        url = save_payload({"kind": "alert", "ip": ip, "payload": payload}, expire=600)
    except Exception as e:
        log.warning("alerts.save_payload_failed: %s", e)

    return IngestResponse(ok=True, accepted=True, stored_url=url)

@router.get("/ping")
async def ping_alerts() -> Dict[str, Any]:
    return {"ok": True, "hmac_required": HMAC_REQUIRED, "rl": {"limit": RL_LIMIT, "window": RL_WINDOW}}

# דיבאג חישוב (ציבורי לפי main.py, אבל כבוי כברירת מחדל)
@router.post("/_debug/alerts-hmac-check", include_in_schema=False)
async def debug_alerts_hmac_check(request: Request) -> Dict[str, Any]:
    if not DEBUG_ALERTS_HMAC_CHECK:
        raise HTTPException(status_code=404, detail="Not Found")
    # חישוב שרת (RAW)
    from security.hmac_verify import _get_secret_bytes, _hmac_hex  # type: ignore
    import base64
    kt = _get_secret_bytes(return_source=True)
    if not kt:
        raise HTTPException(status_code=500, detail="HMAC secret not configured")
    key, key_src, key_is_hex = kt
    raw = await request.body()
    resp = {
        "ok": True,
        "used_key_source": key_src,
        "key_is_hex": key_is_hex,
        "body_len": len(raw),
        "calc_raw": {"hex": _hmac_hex(key, raw), "b64": base64.b64encode(hmac.new(key, raw, hashlib.sha256).digest()).decode()},
        "observed_headers": {
            "X-Webhook-Hmac": request.headers.get("X-Webhook-Hmac"),
            "X-Signature": request.headers.get("X-Signature"),
            "X-Hub-Signature-256": request.headers.get("X-Hub-Signature-256"),
            "X-Webhook-Ts": request.headers.get("X-Webhook-Ts"),
            "Content-Type": request.headers.get("Content-Type"),
        },
    }
    ts = request.headers.get("X-Webhook-Ts")
    if ts:
        msg = (ts + ".").encode() + raw
        resp["calc_with_ts"] = {"ts": ts, "hex": _hmac_hex(key, msg), "note": 'hex of f"{ts}."+RAW'}
    return resp





















