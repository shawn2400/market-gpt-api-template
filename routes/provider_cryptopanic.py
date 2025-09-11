# FILE: routes/provider_cryptopanic.py
from __future__ import annotations
import os, hmac, hashlib, time, json
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Request, Header, HTTPException, Depends
from pydantic import BaseModel

from utils.idempotency import claim as idem_claim
from utils.rate_limit import require_rate_limit
from utils.telegram_api import send_message as telegram_send  # ודא שקיים utils/telegram_api.py עם send_message

router = APIRouter(
    prefix="/provider/cryptopanic",
    tags=["Provider: CryptoPanic"],
    dependencies=[Depends(require_rate_limit(ns="provider_cp",
                                            rpm=int(os.getenv("CP_RPM", "60")),
                                            burst=int(os.getenv("CP_BURST", os.getenv("CP_RPM", "60"))),
                                            by_token_only=False))]
)

# ---- ENV / Policy ----
CP_SECRET = (os.getenv("CP_HMAC_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET") or "").strip()
CP_IP_ALLOW = {ip.strip() for ip in (os.getenv("CP_IP_ALLOWLIST", "")).split(",") if ip.strip()}
CP_IDEMP_TTL = int(os.getenv("CP_IDEMP_TTL_SEC", "600"))
CP_MAX_SKEW = int(os.getenv("CP_MAX_SKEW_SEC", "180"))  # seconds

def _ip_allowed(req: Request) -> bool:
    if not CP_IP_ALLOW:
        return True
    ip = (req.client.host if req.client else "")
    return ip in CP_IP_ALLOW

def _verify_hmac(signature_hex: Optional[str], timestamp: Optional[str], raw: bytes) -> bool:
    if not CP_SECRET:
        return True  # פיתוח בלבד
    if not signature_hex or not timestamp:
        return False
    try:
        ts = int(timestamp)
        if abs(int(time.time()) - ts) > CP_MAX_SKEW:
            return False
    except Exception:
        return False
    try:
        msg = f"{timestamp}.".encode("utf-8") + raw
        mac = hmac.new(CP_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(mac, signature_hex.strip().lower())
    except Exception:
        return False

def _idem_key(sig: Optional[str], ts: Optional[str], provided: Optional[str]) -> str:
    if provided:
        return f"cp:{provided.strip()}"
    base = (sig or "nosig") + ":" + (ts or "nots")
    return f"cp:{hashlib.sha256(base.encode('utf-8')).hexdigest()[:32]}"

# ---- Pydantic payloads ----
class CPCurrency(BaseModel):
    code: Optional[str] = None
    title: Optional[str] = None

class CPItem(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    currencies: Optional[List[CPCurrency]] = None
    kind: Optional[str] = None
    source: Optional[Dict[str, Any]] = None
    votes: Optional[Dict[str, Any]] = None
    published_at: Optional[str] = None

class CPEnvelope(BaseModel):
    item: Optional[CPItem] = None
    __root__: Optional[Dict[str, Any]] = None

def _pull_item(d: Dict[str, Any]) -> Dict[str, Any]:
    if "item" in d and isinstance(d["item"], dict):
        return d["item"]
    return d

@router.get("/ping")
async def ping():
    return {"ok": True, "src": "cryptopanic"}

@router.post("/webhook")
async def webhook(
    request: Request,
    x_provider_signature: Optional[str] = Header(None),
    x_signature: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None),
    x_idempotency_key: Optional[str] = Header(None),
):
    # 1) IP allowlist
    if not _ip_allowed(request):
        raise HTTPException(403, "IP not allowed")

    # 2) HMAC
    raw = await request.body()
    sig = x_provider_signature or x_signature
    if not _verify_hmac(sig, x_timestamp, raw):
        raise HTTPException(401, "Invalid signature")

    # 3) Idempotency
    key = _idem_key(sig, x_timestamp, x_idempotency_key)
    if not idem_claim(key, ttl_sec=CP_IDEMP_TTL):
        return {"ok": True, "duplicate": True}

    # 4) Parse
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    item = _pull_item(payload)
    title = str(item.get("title") or "News").strip()
    url = str(item.get("url") or "").strip()
    kind = str(item.get("kind") or "").strip()
    currencies = item.get("currencies") or []
    if isinstance(currencies, list):
        assets = [c.get("code") for c in currencies if isinstance(c, dict) and c.get("code")]
    else:
        assets = []

    # 5) Notify Telegram
    assets_str = ", ".join(assets) if assets else "-"
    url_line = f"\n🔗 <a href=\"{url}\">link</a>" if url else ""
    kind_tag = f" [{kind}]" if kind else ""
    text = (
        f"📰 <b>CryptoPanic</b>{kind_tag}\n"
        f"• <b>Title:</b> {title}\n"
        f"• <b>Assets:</b> {assets_str}"
        f"{url_line}"
    )
    try:
        await telegram_send(text)
    except Exception:
        pass

    return {"ok": True, "assets": assets, "title": title[:80]}
