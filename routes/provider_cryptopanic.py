# FILE: routes/provider_cryptopanic.py
from __future__ import annotations
import os, time, hmac, hashlib, ipaddress, html
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request, HTTPException, Header, Depends
import httpx

from utils.rate_limit import require_rate_limit
from utils.idempotency import claim as idem_claim
from utils.telegram_api import send_message as tg_send

router = APIRouter(
    prefix="/provider/cryptopanic",
    tags=["Provider: CryptoPanic"],
    # Rate-limit גלובלי לרוט הזה (IP או טוקן; בפועל זה יהיה לפי IP)
    dependencies=[Depends(require_rate_limit("cryptopanic", rpm=int(os.getenv("CP_RPM", "60")),
                                            burst=int(os.getenv("CP_BURST", "60")), by_token_only=False))]
)

# ===== ENV =====
CP_HMAC_SECRET = os.getenv("CP_HMAC_SECRET", "").strip()
CP_IDEMP_TTL_SEC = int(os.getenv("CP_IDEMP_TTL_SEC", "600"))
CP_MAX_SKEW_SEC = int(os.getenv("CP_MAX_SKEW_SEC", "180"))
ALERTS_ANALYSIS_URL = os.getenv("ALERTS_ANALYSIS_URL", "").strip()

# IP allowlist (comma / newline / space separated; supports single IP or CIDR)
def _load_allowlist() -> List[ipaddress._BaseNetwork | ipaddress._BaseAddress]:
    raw = os.getenv("CP_IP_ALLOWLIST", "") or ""
    items: List[str] = []
    for sep in [",", "\n", " "]:
        raw = raw.replace(sep, ",")
    items = [x.strip() for x in raw.split(",") if x.strip()]
    out: List[ipaddress._BaseNetwork | ipaddress._BaseAddress] = []
    for x in items:
        try:
            if "/" in x:
                out.append(ipaddress.ip_network(x, strict=False))
            else:
                out.append(ipaddress.ip_address(x))
        except Exception:
            # מתעלמים משורה שגויה כדי לא לשבור Production
            pass
    return out

_CP_ALLOWLIST = _load_allowlist()

def _client_ip(req: Request) -> str:
    # הערה: מאחורי פרוקסי נקבל X-Forwarded-For
    xff = req.headers.get("X-Forwarded-For") or req.headers.get("x-forwarded-for")
    if xff:
        # לוקחים את הראשון בשרשרת
        return xff.split(",")[0].strip()
    return (req.client.host if req.client else "0.0.0.0")

def _ip_allowed(ip_s: str) -> bool:
    if not _CP_ALLOWLIST:
        # אם הרשימה ריקה — לא נחסום (נוח לפיתוח); בפרודקשן מומלץ להגדיר Allowlist
        return True
    try:
        ip_obj = ipaddress.ip_address(ip_s)
    except Exception:
        return False
    for ent in _CP_ALLOWLIST:
        if isinstance(ent, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            if ip_obj == ent:
                return True
        else:  # network
            if ip_obj in ent:
                return True
    return False

def _const_eq(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a, b)
    except Exception:
        return a == b

def _verify_hmac(sig_header: Optional[str], body: bytes, secret: str) -> bool:
    if not secret:
        # אם אין סוד — לא מאשרים HMAC (נחזיר True כדי לא לשבור אם בחרת לעבוד בלי HMAC)
        return True
    if not sig_header:
        return False
    sig = sig_header.strip()
    if sig.lower().startswith("sha256="):
        sig = sig.split("=", 1)[1].strip()
    calc = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return _const_eq(calc, sig)

def _verify_timestamp(ts_header: Optional[str], max_skew_sec: int) -> bool:
    if not ts_header:
        # אם אין חותמת זמן — לא חוסמים (אפשר לשנות ל־False אם רוצים קשיחות)
        return True
    try:
        ts = int(ts_header)
    except Exception:
        return False
    now = int(time.time())
    return abs(now - ts) <= max_skew_sec

def _mk_summary(payload: Dict[str, Any]) -> str:
    # בונה טקסט קריא לטלגרם ללא הסתמכות על סכימה ספציפית
    title = str(
        payload.get("title")
        or payload.get("headline")
        or payload.get("item", {}).get("title")
        or payload.get("items", [{}])[0].get("title")
        or "CryptoPanic: event"
    )
    url = str(
        payload.get("url")
        or payload.get("item", {}).get("url")
        or payload.get("items", [{}])[0].get("url")
        or ""
    )
    cur = payload.get("currencies") or payload.get("assets") or payload.get("symbols")
    if isinstance(cur, list):
        cur = ", ".join(map(str, cur))
    kind = payload.get("kind") or payload.get("type") or "news"
    title = html.escape(title)
    url = html.escape(url)
    cur = html.escape(str(cur or "-"))
    kind = html.escape(str(kind))
    out = f"📰 <b>CryptoPanic</b> | <i>{kind}</i>\n<b>{title}</b>"
    if url:
        out += f"\n🔗 <a href=\"{url}\">link</a>"
    out += f"\n💱 {cur}"
    return out

@router.get("/ping")
async def ping():
    return {"ok": True, "src": "cryptopanic"}

@router.get("/debug")
async def debug():
    return {
        "ok": True,
        "allowlist": [str(x) for x in _CP_ALLOWLIST] or None,
        "hmac": bool(CP_HMAC_SECRET),
        "analysis_forward": bool(ALERTS_ANALYSIS_URL),
    }

@router.post("/webhook")
async def webhook(
    request: Request,
    x_signature: Optional[str] = Header(None),      # sha256=<hex> או רק hex
    x_timestamp: Optional[str] = Header(None),      # seconds
    x_idempotency_key: Optional[str] = Header(None)
):
    # 1) Allowlist ל־IP
    ip = _client_ip(request)
    if not _ip_allowed(ip):
        raise HTTPException(status_code=403, detail=f"ip not allowed: {ip}")

    # 2) קריאת גוף הבקשה (raw + json)
    try:
        raw = await request.body()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid body")
    # 3) אימות HMAC
    if not _verify_hmac(x_signature, raw, CP_HMAC_SECRET):
        raise HTTPException(status_code=401, detail="invalid signature")
    # 4) בדיקת זמן
    if not _verify_timestamp(x_timestamp, CP_MAX_SKEW_SEC):
        raise HTTPException(status_code=401, detail="timestamp skew too large")

    # 5) Idempotency
    idem_key = x_idempotency_key or hashlib.sha256(raw).hexdigest()
    if not idem_claim(f"cp:{idem_key}", ttl_sec=CP_IDEMP_TTL_SEC):
        # כפול — מחזירים 200 כדי לא לעורר ריטריים אין-סופיים אצל הספק
        return {"ok": True, "duplicate": True}

    # 6) JSON
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    # 7) שליחת תקציר לטלגרם (לא חוסם; אם נכשל ממשיכים)
    try:
        text = _mk_summary(payload)
        await tg_send(text, parse_mode="HTML", disable_preview=True)
    except Exception:
        pass

    # 8) פורוורד אופציונלי ל־/alerts/analysis
    if ALERTS_ANALYSIS_URL:
        try:
            async with httpx.AsyncClient(timeout=8.0) as cli:
                await cli.post(ALERTS_ANALYSIS_URL, json={
                    "provider": "cryptopanic",
                    "payload": payload,
                    "received_ip": ip,
                    "ts": int(time.time()),
                })
        except Exception:
            # לא מפילים את הוובהוק
            pass

    return {"ok": True, "provider": "cryptopanic", "id": idem_key}
