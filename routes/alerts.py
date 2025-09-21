# routes/alerts.py
from __future__ import annotations
import os, json, logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from utils.security import verify_request_hmac, verify_bearer
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

class IngestResponse(BaseModel):
    ok: bool = True
    accepted: bool = True
    dedup: bool = False
    stored_url: Optional[str] = None
    reason: Optional[str] = None

@router.post("/ingest", response_model=IngestResponse, summary="Ingest trading alerts (TradingView / custom)")
async def ingest_alert(request: Request) -> IngestResponse:
    # ── Rate limit per IP ──
    ip = request.client.host if request.client else "unknown"
    allowed, remaining = await rl_allow("alerts", ip, limit=RL_LIMIT, window_sec=RL_WINDOW)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # ── Auth ──
    if HMAC_REQUIRED:
        ok, reason = await verify_request_hmac(request)
        if not ok:
            raise HTTPException(status_code=401, detail=f"HMAC verify failed: {reason}")
    else:
        # אם HMAC לא חובה – ננסה Bearer; אם גם הוא לא קיים, נאפשר (development)
        if not verify_bearer(request):
            if os.getenv("ALLOW_ALERTS_WITHOUT_AUTH", "0").lower() not in ("1", "true", "yes", "on"):
                raise HTTPException(status_code=401, detail="Unauthorized")

    # ── Body ──
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
    return {"ok": True, "hmac_required": HMAC_REQUIRED, "rl": {"limit": RL_LIMIT, "window": RL_WINDOW}}



















