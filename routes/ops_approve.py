# routes/ops_approve.py
from __future__ import annotations

import os
import hmac
import json
import hashlib
import base64
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

# אופציונלי: שימוש לוגי/אכסון בקשות (אם קיים), עם פולבאק שקט
try:
    from utils.trade_executor import ConfirmStore  # type: ignore
except Exception:
    try:
        from utils.auto_executor import ConfirmStore  # type: ignore
    except Exception:
        class ConfirmStore:  # type: ignore
            pending: Dict[str, Any] = {}
            @classmethod
            def flush_all(cls) -> None:
                cls.pending = {}
            flush = reset = flush_all

router = APIRouter()

# ---------- עזר חתימה ----------

def _secret_bytes() -> Tuple[bytes, str]:
    """
    העדפה: WEBHOOK_HMAC_SECRET; אם חסר → OPS_SIGN_SECRET.
    אם המחרוזת באורך 64 תווים — ננסה לפרש כ-HEX, אחרת UTF-8.
    """
    raw = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()
    used = "WEBHOOK_HMAC_SECRET" if os.getenv("WEBHOOK_HMAC_SECRET") else "OPS_SIGN_SECRET"
    if len(raw) == 64:
        try:
            return bytes.fromhex(raw), used
        except Exception:
            pass
    return raw.encode("utf-8"), used


def _clean_sig(v: Optional[str]) -> str:
    v = (v or "").strip()
    # תומך בפורמט GitHub: "sha256=<hex>"
    if v.lower().startswith("sha256="):
        v = v.split("=", 1)[1].strip()
    return v


def _read_body_and_verify(headers: Dict[str, str], body: bytes) -> Tuple[bool, Dict[str, str], Dict[str, str], str, str]:
    secret, used_name = _secret_bytes()
    digest = hmac.new(secret, body, hashlib.sha256).digest()
    hex_srv = digest.hex()
    b64_srv = base64.b64encode(digest).decode()

    # ניקוי כותרות מועמדות
    raw_headers = {
        "x-signature": headers.get("x-signature", ""),
        "x-webhook-hmac": headers.get("x-webhook-hmac", ""),
        "x-hub-signature-256": headers.get("x-hub-signature-256", ""),
    }
    clean_headers = {k: _clean_sig(v) for k, v in raw_headers.items()}

    # השוואה
    match_hex = any(_clean_sig(v).lower() == hex_srv for v in raw_headers.values() if v)
    match_b64 = any(_clean_sig(v) == b64_srv for v in raw_headers.values() if v)
    ok = match_hex or match_b64

    return ok, raw_headers, clean_headers, hex_srv, b64_srv


# ---------- מודל/ולידציה קלה ----------

def _parse_json_or_400(raw: bytes) -> Dict[str, Any]:
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")


def _validate_payload(p: Dict[str, Any]) -> None:
    """
    ולידציה מינימלית בלבד—משאירה את הבדיקות העמוקות לשכבות אחרות.
    דורשת לפחות: action, ticket_id, symbol, side, qty
    """
    required = ["action", "ticket_id", "symbol", "side", "qty"]
    missing = [k for k in required if k not in p]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing required fields: {', '.join(missing)}")


# ---------- ראוטים ----------

@router.post("/ops/approve", tags=["Ops"])
async def ops_approve(request: Request):
    """
    נקודת אישור *ללא* חתימה (לשימוש פנימי/בדיקות).
    """
    raw = await request.body()
    payload = _parse_json_or_400(raw)
    _validate_payload(payload)

    # אופציונלי: שמירת הבקשה ב-ConfirmStore
    try:
        tid = str(payload.get("ticket_id", ""))
        ConfirmStore.pending[tid] = {"payload": payload, "approved": True}
    except Exception:
        pass

    return JSONResponse({"ok": True, "approved": True, "echo": payload})


@router.post("/ops/approve/signed", tags=["Ops"])
async def ops_approve_signed(request: Request):
    """
    נקודת אישור *חתומה*.
    תומך בכותרות:
      - X-Signature  (hex)
      - X-Webhook-Hmac (base64/hex)
      - X-Hub-Signature-256 (sha256=<hex>)
    """
    raw = await request.body()
    ok, raw_hdrs, clean_hdrs, hex_srv, b64_srv = _read_body_and_verify(request.headers, raw)
    if not ok:
        # מחזירים 401 כדי לא להדליף את הסוד—עם פרטי דיבוג עדינים
        raise HTTPException(status_code=401, detail={"error": "Bad signature", "server_hex": hex_srv, "server_b64": b64_srv})

    payload = _parse_json_or_400(raw)
    _validate_payload(payload)

    # אופציונלי: שמירת הבקשה ב-ConfirmStore
    try:
        tid = str(payload.get("ticket_id", ""))
        ConfirmStore.pending[tid] = {"payload": payload, "approved": True, "signed": True}
    except Exception:
        pass

    return JSONResponse({"ok": True, "approved": True, "echo": payload})


@router.post("/ops/reject", tags=["Ops"])
async def ops_reject(request: Request):
    """
    דחיית טיקט (לא מחייב חתימה).
    """
    raw = await request.body()
    payload = _parse_json_or_400(raw)
    ticket_id = str(payload.get("ticket_id", "")) or ""
    if not ticket_id:
        raise HTTPException(status_code=422, detail="Missing ticket_id")

    try:
        # מסמנים כנדחה
        ConfirmStore.pending[ticket_id] = {"payload": payload, "approved": False}
    except Exception:
        pass

    return JSONResponse({"ok": True, "approved": False, "echo": payload})








