# routes/ops_guard.py
from __future__ import annotations

import os, hmac, hashlib, time, json, logging
from typing import Dict, Any, Optional
from urllib.parse import urlencode, quote_plus

from fastapi import APIRouter, Query, HTTPException
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_401_UNAUTHORIZED

router = APIRouter(tags=["Ops"])
logger = logging.getLogger("algogpt.ops_guard")

# =======================
#  Degrade/TTL/Alerts tick (כמו אצלך, נשמר)
# =======================
try:
    from utils.ops_guard import ops_tick  # type: ignore
except Exception:
    async def ops_tick(**kw):  # type: ignore
        return None

@router.get("/ops/guard/tick", include_in_schema=False)
async def ops_guard_tick(
    ws_reconnects: Optional[int] = Query(None, description="מספר Reconnects של ה־WS בתקופה האחרונה"),
    price_ttl_sec: Optional[float] = Query(None, description="גיל עדכון מחיר אחרון (שניות)"),
    exec_batch_timeout: bool = Query(False, description="האם היה Timeout בבאץ' ביצוע לאחרונה"),
):
    """
    נקודת איסוף רכה למצב אופס — מעדכנת את מנגנון השמירה (TTL / עומסים / Degrade Mode).
    (מוגן ע״י האימות הגלובלי של ה־API; לא נוסף ל־public paths.)
    """
    await ops_tick(
        ws_reconnects=ws_reconnects,
        price_ttl_sec=price_ttl_sec,
        exec_batch_timeout=exec_batch_timeout,
    )
    return {
        "ok": True,
        "ws_reconnects": ws_reconnects,
        "price_ttl_sec": price_ttl_sec,
        "exec_batch_timeout": exec_batch_timeout,
    }

# =======================
#  חתימה HMAC לקישורי approve/reject
# =======================
OPS_SIGN_SECRET = os.getenv("OPS_SIGN_SECRET") or os.getenv("WEBHOOK_HMAC_SECRET") or ""
SIGN_TTL_SEC = int(os.getenv("OPS_SIGN_TTL_SEC", "300"))  # ברירת מחדל 5 דק'
PUBLIC_HOST = (os.getenv("PUBLIC_HOST") or os.getenv("PRIMARY_PUBLIC_HOST") or "").rstrip("/")

if not OPS_SIGN_SECRET:
    logger.warning({"event": "ops_sign_secret_missing", "detail": "OPS_SIGN_SECRET/WEBHOOK_HMAC_SECRET not set"})

# שליחת טלגרם (best-effort)
try:
    from utils.telegram_notifier import _send as send_telegram_raw  # type: ignore
except Exception:
    def send_telegram_raw(*args, **kwargs):
        logger.warning({"event": "tg_send_stub", "args": args, "kwargs": kwargs})

def _hmac(payload: str) -> str:
    if not isinstance(payload, (bytes, bytearray)):
        payload = payload.encode("utf-8")
    return hmac.new(OPS_SIGN_SECRET.encode("utf-8"), payload, hashlib.sha256).hexdigest()

def _verify(payload: str, sig: str) -> bool:
    try:
        return hmac.compare_digest(_hmac(payload), sig)
    except Exception:
        return False

def _now_ms() -> int:
    return int(time.time() * 1000)

# לשמור סדר קבוע בשדות כדי שהחתימה תהיה יציבה
_CANON_FIELDS = ("action","ticket_id","symbol","side","qty","price","lev","ttl_ms","ts_ms","extra")

def _canon_payload(d: Dict[str, Any]) -> str:
    dd = {k: d.get(k) for k in _CANON_FIELDS if k in d}
    return json.dumps(dd, separators=(",", ":"), ensure_ascii=False)

def build_signed_link(
    *,
    action: str,                 # "approve" / "reject"
    ticket_id: str,
    symbol: str,
    side: str,                   # BUY/SELL
    qty: float | int | str,
    price: float | int | str | None = None,
    lev: int | None = None,
    ttl_ms: int | None = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """
    בונה URL חתום ל-approve/reject. מחזיר לינק מלא לשימוש בכפתורי טלגרם.
    """
    if not PUBLIC_HOST:
        raise RuntimeError("PUBLIC_HOST not configured")
    if not OPS_SIGN_SECRET:
        raise RuntimeError("OPS_SIGN_SECRET/WEBHOOK_HMAC_SECRET not configured")

    ts_ms = _now_ms()
    ttl_ms = int(ttl_ms if ttl_ms and ttl_ms > 0 else SIGN_TTL_SEC * 1000)

    payload = {
        "action": action.lower().strip(),
        "ticket_id": str(ticket_id),
        "symbol": symbol.upper().strip(),
        "side": side.upper().strip(),
        "qty": str(qty),
        "price": str(price) if price is not None else None,
        "lev": int(lev) if lev is not None else None,
        "ttl_ms": ttl_ms,
        "ts_ms": ts_ms,
        "extra": extra or {},
    }
    pstr = _canon_payload(payload)
    sig = _hmac(pstr)

    qp = {
        "ticket_id": payload["ticket_id"],
        "symbol": payload["symbol"],
        "side": payload["side"],
        "qty": payload["qty"],
        "price": payload["price"] if payload["price"] is not None else "",
        "lev": payload["lev"] if payload["lev"] is not None else "",
        "ttl_ms": ttl_ms,
        "ts_ms": ts_ms,
        "sig": sig,
    }
    path = f"/ops/{'approve' if action.lower()=='approve' else 'reject'}"
    return f"{PUBLIC_HOST}{path}?{urlencode(qp, quote_via=quote_plus)}"

def send_ticket_with_buttons(
    *,
    chat_id: str | int,
    ticket_id: str,
    text: str,
    symbol: str,
    side: str,
    qty: float | int | str,
    price: float | int | str | None = None,
    lev: int | None = None,
    ttl_ms: int | None = None,
    extra: Optional[Dict[str, Any]] = None,
):
    """
    שולח הודעת טלגרם עם כפתורי אישור/ביטול חתומים (inline keyboard).
    אם utils.telegram_notifier._send תומך ב-reply_markup — תופיע מקלדת.
    """
    try:
        approve_url = build_signed_link(
            action="approve", ticket_id=ticket_id, symbol=symbol, side=side,
            qty=qty, price=price, lev=lev, ttl_ms=ttl_ms, extra=extra
        )
        reject_url = build_signed_link(
            action="reject", ticket_id=ticket_id, symbol=symbol, side=side,
            qty=qty, price=price, lev=lev, ttl_ms=ttl_ms, extra=extra
        )
    except Exception as e:
        logger.error({"event": "ticket_build_failed", "error": str(e)})
        approve_url = reject_url = None

    rm = {"inline_keyboard": [[
        {"text": "✅ אישור", "url": approve_url},
        {"text": "❌ ביטול", "url": reject_url},
    ]]}
    send_telegram_raw(text=text, chat_id=str(chat_id), reply_markup=rm)

def _verify_request(params: Dict[str, Any], action: str) -> Dict[str, Any]:
    """
    מאמת שהבקשה חתומה ותקפה בזמן. זורק 401/400 אם לא.
    """
    payload = {
        "action": action,
        "ticket_id": params.get("ticket_id"),
        "symbol": (params.get("symbol") or "").upper(),
        "side": (params.get("side") or "").upper(),
        "qty": params.get("qty"),
        "price": params.get("price") if params.get("price") not in (None, "",) else None,
        "lev": int(params["lev"]) if str(params.get("lev") or "").strip().isdigit() else None,
        "ttl_ms": int(params.get("ttl_ms") or 0),
        "ts_ms": int(params.get("ts_ms") or 0),
        "extra": {},
    }
    sig = params.get("sig") or ""
    pstr = _canon_payload(payload)

    ok_sig = bool(OPS_SIGN_SECRET) and _verify(pstr, sig)
    now = _now_ms()
    ttl_ms = payload["ttl_ms"] or (SIGN_TTL_SEC * 1000)
    expired = (now - (payload["ts_ms"] or 0)) > ttl_ms

    info = {
        "action": action,
        "payload": payload,
        "ok_sig": ok_sig,
        "expired": expired,
        "now": now,
        "ts_ms": payload["ts_ms"],
        "ttl_ms": ttl_ms,
    }
    if not ok_sig:
        logger.warning({"event": "verify_fail", **info, "reason": "bad_signature"})
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="bad_signature")
    if expired:
        logger.warning({"event": "verify_fail", **info, "reason": "link_expired"})
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="link_expired")

    logger.info({"event": "verify_ok", **info})
    return payload

# =======================
#  Endpoints: approve / reject
#  (מכוון להיות מחוץ לדוקס; אם תרצה – שנה include_in_schema=True)
# =======================
@router.get("/ops/approve", include_in_schema=False, summary="Approve trade (signed)")
async def ops_approve(
    ticket_id: str = Query(...),
    symbol: str = Query(...),
    side: str = Query(...),
    qty: str = Query(...),
    price: Optional[str] = Query(None),
    lev: Optional[str] = Query(None),
    ttl_ms: Optional[int] = Query(None),
    ts_ms: int = Query(...),
    sig: str = Query(...),
):
    payload = _verify_request(
        {
            "ticket_id": ticket_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "lev": lev,
            "ttl_ms": ttl_ms,
            "ts_ms": ts_ms,
            "sig": sig,
        },
        action="approve",
    )

    # כאן אפשר לבצע פעולה אמיתית (לדוגמה: לפתוח הזמנה/להכניס לתור executor).
    logger.info({"event": "approved", "ticket_id": ticket_id, "payload": payload})
    return {"ok": True, "action": "approved", "ticket_id": ticket_id, "payload": payload}

@router.get("/ops/reject", include_in_schema=False, summary="Reject trade (signed)")
async def ops_reject(
    ticket_id: str = Query(...),
    symbol: str = Query(...),
    side: str = Query(...),
    qty: str = Query(...),
    price: Optional[str] = Query(None),
    lev: Optional[str] = Query(None),
    ttl_ms: Optional[int] = Query(None),
    ts_ms: int = Query(...),
    sig: str = Query(...),
):
    payload = _verify_request(
        {
            "ticket_id": ticket_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "lev": lev,
            "ttl_ms": ttl_ms,
            "ts_ms": ts_ms,
            "sig": sig,
        },
        action="reject",
    )

    # כאן מסמנים דחייה/מבטלים וכו'.
    logger.info({"event": "rejected", "ticket_id": ticket_id, "payload": payload})
    return {"ok": True, "action": "rejected", "ticket_id": ticket_id, "payload": payload}

# =======================
#  Self test (מוסתר)
# =======================
@router.get("/ops/_test_link", include_in_schema=False)
async def _test_link():
    try:
        url_ok = build_signed_link(
            action="approve", ticket_id="T123", symbol="BTCUSDT",
            side="BUY", qty="0.01", price="65000", lev=10
        )
        return {"ok": True, "sample": url_ok}
    except Exception as e:
        return {"ok": False, "error": str(e)}

