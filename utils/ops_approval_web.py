# FILE: utils/ops_approval_web.py
from __future__ import annotations
import os, time, json, hmac, hashlib, re
from typing import Any, Dict, Optional, List, Set

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import aiohttp

try:
    import redis  # type: ignore
except Exception as e:
    raise SystemExit(f"redis library required: {e}")

APP_TITLE = "Ops Approval Webhook"
app = FastAPI(title=APP_TITLE)

# --------- ENV ---------
REDIS_URL_ENV = os.getenv("REDIS_URL", "")
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").encode() if os.getenv("WEBHOOK_HMAC_SECRET") else None
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
APPROVAL_PUBSUB_CHANNEL = os.getenv("APPROVAL_PUBSUB_CHANNEL", "ops:ticket:events")

def _as_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1","true","yes","on","y")

# Enforcements for two-man rule
REQUIRE_UNIQUE_APPROVERS = _as_bool(os.getenv("REQUIRE_UNIQUE_APPROVERS", "1"), True)  # דרוש מאשרים שונים
REQUIRE_APPROVER_ID      = _as_bool(os.getenv("REQUIRE_APPROVER_ID", "1"), True)       # חייב להעביר 'by'
ALLOW_MISSING_HMAC       = _as_bool(os.getenv("ALLOW_MISSING_HMAC", "0"), False)       # לא מומלץ
# רשימת מאשרים מותרת (אופציונלי). ניתן לשים מזהי טלגרם/אימייל/שם משתמש.
ALLOWLIST_RAW = os.getenv("APPROVER_ALLOWLIST", "")  # e.g. "449087907,dev1@example.com,alice"
ALLOWLIST: Set[str] = set(x.strip() for x in ALLOWLIST_RAW.split(",") if x.strip())

# --------- runtime holders ---------
_redis: Optional[redis.Redis] = None
_http: Optional[aiohttp.ClientSession] = None

# --------- helpers ---------
def _clean_redis_url(u: str) -> str:
    if not u:
        return u
    u = u.strip().strip('"').strip("'").strip()
    u = u.replace("\\n", "").rstrip("\n").strip()
    if u.startswith("//") and "keyvalue.render.com" in u:
        u = "rediss:" + u
    if "keyvalue.render.com" in u and not u.startswith("rediss://"):
        u = "rediss://" + u.split("://", 1)[-1]
    if re.search(r"@red-[a-z0-9]+:6379$", u) and "keyvalue.render.com" not in u:
        m = re.match(r"^redis[s]?://([^@]+)@[^:]+:\d+$", u)
        if m:
            auth = m.group(1)
            u = f"rediss://{auth}@frankfurt-keyvalue.render.com:6379"
    return u

async def send_telegram(text: str):
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID and _http):
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with _http.post(url, json=payload) as r:
            await r.text()
    except Exception:
        pass

def _sign_params(params: Dict[str, str]) -> str:
    if not WEBHOOK_HMAC_SECRET:
        return ""
    s = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hmac.new(WEBHOOK_HMAC_SECRET, s.encode(), hashlib.sha256).hexdigest()

def _html(s: str) -> str:
    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _ticket_key(ticket_id: str) -> str:
    return f"ops:ticket:{ticket_id}"

async def _load_ticket(ticket_id: str) -> Optional[Dict[str, Any]]:
    if not _redis:
        return None
    v = _redis.get(_ticket_key(ticket_id))
    return json.loads(v) if v else None

def _save_ticket(ticket: Dict[str, Any], ttl_s: int):
    if not _redis:
        return
    _redis.setex(_ticket_key(ticket["id"]), max(60, ttl_s), json.dumps(ticket))

def _publish_event(ticket_id: str, status: str, approvals: int, require: int, version: str = "", approvers: List[str] | None = None):
    try:
        if _redis:
            _redis.publish(APPROVAL_PUBSUB_CHANNEL, json.dumps({
                "id": ticket_id,
                "status": status,
                "approvals": int(approvals),
                "require": int(require),
                "approvers": approvers or [],
                "version": version,
                "ts": int(time.time())
            }))
    except Exception:
        pass

def _sanitize_approver(s: str) -> str:
    s = s.strip()
    # קצר ונקי לתצוגה/אחסון
    if len(s) > 128:
        s = s[:128]
    return s

# --------- lifecycle ---------
@app.on_event("startup")
async def _startup():
    global _redis, _http
    _http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    url = _clean_redis_url(REDIS_URL_ENV)
    if not url:
        raise RuntimeError("REDIS_URL is required for approval webhook")
    _redis = redis.Redis.from_url(url, decode_responses=True)
    try:
        _redis.ping()
    except Exception as e:
        raise RuntimeError(f"Redis ping failed: {e}")

@app.on_event("shutdown")
async def _shutdown():
    global _http
    if _http:
        await _http.close()
        _http = None

# --------- routes ---------
@app.get("/health", response_class=JSONResponse)
async def health():
    ok = False
    try:
        ok = bool(_redis and _redis.ping())
    except Exception:
        ok = False
    return JSONResponse({
        "ok": ok,
        "pubsub_channel": APPROVAL_PUBSUB_CHANNEL,
        "require_unique_approvers": REQUIRE_UNIQUE_APPROVERS,
        "require_approver_id": REQUIRE_APPROVER_ID,
        "allowlist_enabled": bool(ALLOWLIST),
    })

# Render "Advanced > Health Check Path" לעיתים מוגדר /healthz
@app.get("/healthz", response_class=JSONResponse)
async def healthz():
    return await health()

@app.get("/ops/approve", response_class=HTMLResponse)
async def approve(req: Request):
    """
    GET /ops/approve?action=approve|reject&ticket_id=...&expires=...&require=2&version=...&sig=&by=
    - אימות HMAC (אם הוגדר סוד)
    - two-man rule אמיתי: מונים מאשרים ייחודיים (approvers)
    - allowlist אופציונלי (APPROVER_ALLOWLIST)
    - עדכון Ticket ב-Redis + פרסום Pub/Sub + הודעת טלגרם
    """
    q = dict(req.query_params)
    required = ["action", "ticket_id", "expires", "require", "version"]
    if WEBHOOK_HMAC_SECRET and not ALLOW_MISSING_HMAC:
        required.append("sig")
    for k in required:
        if k not in q:
            raise HTTPException(status_code=400, detail=f"missing param: {k}")

    action = q["action"]
    ticket_id = q["ticket_id"]
    by = _sanitize_approver(q.get("by", ""))

    try:
        exp = int(q["expires"])
        req_needed = max(1, int(q["require"]))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid expires/require")

    now = int(time.time())
    if exp < now:
        return HTMLResponse(f"<h2>⏱️ Link expired</h2><p>ticket <code>{_html(ticket_id)}</code></p>", status_code=410)

    # HMAC check (optional)
    if WEBHOOK_HMAC_SECRET and not ALLOW_MISSING_HMAC:
        to_sign = {k: q[k] for k in q if k != "sig"}
        expected = _sign_params(to_sign)
        if not hmac.compare_digest(expected, q.get("sig","")):
            raise HTTPException(status_code=401, detail="bad signature")

    # Enforce presence of 'by' when needed
    if REQUIRE_APPROVER_ID and req_needed > 1 and not by:
        raise HTTPException(status_code=400, detail="missing 'by' (approver id)")

    # Allowlist (optional)
    if ALLOWLIST and by:
        if by not in ALLOWLIST:
            return HTMLResponse(
                f"<h2>🚫 Unauthorized approver</h2>"
                f"<p><b>{_html(by)}</b> is not in allowlist.</p>",
                status_code=403
            )

    # Load/Create ticket
    ticket = await _load_ticket(ticket_id)
    if not ticket:
        ticket = {
            "id": ticket_id,
            "status": "pending",
            "require": req_needed,
            "approvals": 0,
            "approvers": [],            # list[str]
            "rejected_by": [],          # list[str]
            "created_at": now,
            "expires_at": exp,
            "proposal": {"version": q.get("version","")},
        }

    # normalize
    try:
        approvers: List[str] = list(dict.fromkeys(ticket.get("approvers", [])))  # unique keep order
    except Exception:
        approvers = []
    rejected_by: List[str] = list(dict.fromkeys(ticket.get("rejected_by", [])))

    remaining = max(30, exp - now)

    if action == "approve":
        # two-man rule: count unique approvers
        if by:
            if (not REQUIRE_UNIQUE_APPROVERS) or (by not in approvers):
                approvers.append(by)
        # compute approvals as unique count (even if 'by' ריק, נשאר כמו שהיה)
        approvals = len(approvers)
        require = int(ticket.get("require", req_needed))
        status = "approved" if approvals >= require else "pending"
        ticket.update({
            "approvers": approvers,
            "approvals": approvals,
            "require": require,
            "status": status,
        })
        verb = f"✅ APPROVED ({approvals}/{require})"
    elif action == "reject":
        if by and by not in rejected_by:
            rejected_by.append(by)
        ticket.update({
            "status": "rejected",
            "rejected_by": rejected_by
        })
        verb = "❌ REJECTED"
    else:
        raise HTTPException(status_code=400, detail="unknown action")

    _save_ticket(ticket, remaining)
    version = q.get("version", "")
    _publish_event(ticket["id"], ticket["status"], ticket.get("approvals", 0), ticket.get("require", 1), version, approvers=ticket.get("approvers", []))

    who = by or q.get("by","unknown")
    await send_telegram(
        f"🔐 <b>Change approval</b> | <code>{_html(ticket_id)}</code>\n"
        f"{verb} | by: <code>{_html(who)}</code>\n"
        f"Version: <code>{_html(version)}</code>\n"
        f"Status: <b>{_html(ticket['status'])}</b>"
    )

    extra = ""
    if ticket["status"] == "approved":
        extra = "<p>System may proceed (supervisor will continue immediately).</p>"
    elif ticket["status"] == "pending":
        extra = f"<p>Waiting for more approvals: {ticket.get('approvals',0)}/{ticket.get('require',1)}.</p>"

    return HTMLResponse(
        f"<h2>{verb}</h2>"
        f"<p>Ticket: <code>{_html(ticket_id)}</code></p>"
        f"<p>Status: <b>{_html(ticket['status'])}</b></p>"
        f"{extra}",
        status_code=200
    )

@app.get("/ops/ticket/{ticket_id}", response_class=JSONResponse)
async def get_ticket(ticket_id: str):
    t = await _load_ticket(ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="ticket not found")
    return JSONResponse(t)

# Local dev
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT","10000")))




