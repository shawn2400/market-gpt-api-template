# routes/telegram_push_status.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, re, json, httpx, asyncio, time
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/telegram", tags=["Telegram"])

# ==== ENV ====
BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
ADMIN_IDS = {x.strip() for x in (os.getenv("TELEGRAM_ADMIN_IDS") or "").split(",") if x.strip()}
WEBHOOK_SECRET = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()

# לאן לדחוף את ה-snapshot
BASE = os.getenv("INTERNAL_BASE") or os.getenv("PUBLIC_HOST") or "http://127.0.0.1:10000"
SNAP_URL = f"{BASE.rstrip('/')}/public/trade/snapshot"
BEARER = (os.getenv("API_BEARER_TOKEN_ACTION") or os.getenv("API_BEARER_TOKEN") or "").strip()

# לשליחת תשובת OK בטלגרם (רשות)
SEND_CONFIRM = (os.getenv("TELEGRAM_SEND_ENABLE") or "1").strip() in ("1","true","yes","on")

# ==== helpers ====
def _is_admin(update: Dict[str, Any]) -> bool:
    try:
        uid = str(update["message"]["from"]["id"])
        return (not ADMIN_IDS) or (uid in ADMIN_IDS)
    except Exception:
        return False

def _auth_ok(secret: str | None) -> bool:
    if not WEBHOOK_SECRET:  # אם לא הוגדר, נוותר על אימות סוד כתוספת
        return True
    return (secret or "").strip() == WEBHOOK_SECRET

async def _tg_send(chat_id: int, text: str) -> None:
    if not (BOT_TOKEN and SEND_CONFIRM):
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=5.0) as cli:
        try:
            await cli.post(url, json={"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML"})
        except Exception:
            pass

def _parse_after_command(txt: str) -> Dict[str, Any]:
    """
    תומך בשתי תבניות:
    1) JSON מלא אחרי הפקודה:
       /push_status { "symbol":"BTCUSDT", "side":"BUY", "entry":107000, ... }
    2) key=value פשוט:
       /push_status BTCUSDT BUY entry=107000 last=107200 sl=106500 tp1=107800 tp2=108400 tp3=109500 low=... high=...
    """
    # נסה JSON:
    m = re.search(r"/push_status\s+(?P<json>\{.*\})\s*$", txt, re.S | re.I)
    if m:
        try:
            body = json.loads(m.group("json"))
            return body if isinstance(body, dict) else {}
        except Exception:
            pass

    # נסה מפתחות key=value:
    # שלב 1: גרור טוקנים (מופרדים ברווחים)
    parts = txt.split()
    # מצא היכן מתחיל הפליילוד
    try:
        idx = parts.index("/push_status")
    except ValueError:
        try:
            # ייתכן שהבוט באזכור: /push_status@YourBot
            idx = next(i for i, p in enumerate(parts) if p.startswith("/push_status"))
        except Exception:
            idx = -1
    params = parts[idx+1:] if idx >= 0 else []

    body: Dict[str, Any] = {}
    # אם שני הראשונים נראים כמו SYMBOL + SIDE
    if len(params) >= 2 and re.fullmatch(r"[A-Z0-9_]+", params[0], re.I) and params[1].upper() in ("BUY","SELL","LONG","SHORT"):
        body["symbol"] = params[0].upper()
        body["side"] = "BUY" if params[1].upper() in ("BUY","LONG") else "SELL"
        kvs = params[2:]
    else:
        kvs = params

    # פרס מפתחות
    for tok in kvs:
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        k = k.strip().lower()
        v = v.strip()
        if not k:
            continue
        # המספרים
        if k in ("entry","entry_price","last","sl","sl_price","tp1","tp2","tp3","low","high"):
            try:
                body[k] = float(v)
            except Exception:
                pass
        elif k in ("symbol","side"):
            body[k] = v
        else:
            # תמיכה ב-nested פשטני: eta.tp1_sec=600
            if "." in k:
                root, child = k.split(".", 1)
                if root not in body or not isinstance(body[root], dict):
                    body[root] = {}
                try:
                    body[root][child] = float(v)
                except Exception:
                    body[root][child] = v
            else:
                body[k] = v

    # הפוך tp1/2/3 לרשימת tp אם צריך
    if any(k in body for k in ("tp1","tp2","tp3")) and "tp" not in body:
        tp_list = []
        for key in ("tp1","tp2","tp3"):
            val = body.get(key, None)
            if isinstance(val, (int,float)):
                tp_list.append({"stopPrice": float(val)})
        if tp_list:
            body["tp"] = tp_list

    return body

def _validate_min(body: Dict[str, Any]) -> None:
    if not (body.get("symbol") and body.get("side")):
        raise ValueError("Missing required: symbol, side")

async def _push_snapshot(body: Dict[str, Any], key_override: Optional[str] = None) -> Dict[str, Any]:
    if not BEARER:
        raise RuntimeError("Missing Bearer token (API_BEARER_TOKEN_ACTION/API_BEARER_TOKEN)")
    headers = {"Authorization": f"Bearer {BEARER}", "Content-Type": "application/json"}
    url = SNAP_URL if not key_override else (SNAP_URL + f"?key={key_override}")
    async with httpx.AsyncClient(timeout=6.0) as cli:
        r = await cli.post(url, headers=headers, json=body)
        r.raise_for_status()
        return r.json()

@router.post("/webhook", summary="Telegram webhook: handles /push_status and pushes snapshot")
async def telegram_webhook(request: Request, secret: Optional[str] = Query(default=None)):
    if not _auth_ok(secret):
        raise HTTPException(status_code=401, detail="bad webhook secret")

    update = await request.json()
    # רק הודעות טקסט
    msg = (update.get("message") or update.get("edited_message")) or {}
    text = (msg.get("text") or "").strip()
    chat_id = msg.get("chat", {}).get("id")

    # אם לא טקסט / אין /push_status — החזר OK (נייטרלי)
    if not text or "/push_status" not in text:
        return JSONResponse({"ok": True, "skipped": True})

    if not _is_admin(update):
        if chat_id: await _tg_send(chat_id, "❌ Not allowed.")
        raise HTTPException(status_code=403, detail="not admin")

    try:
        body = _parse_after_command(text)
        _validate_min(body)

        # תמיכה באופציה של key=... בתוך הפקודה: /push_status ... key=ops:trade:open:BTCUSDT
        key_override = None
        mkey = re.search(r"(?:\s|^)key=(?P<key>[\w:\-\.]+)(?:\s|$)", text, re.I)
        if mkey:
            key_override = mkey.group("key")

        res = await _push_snapshot(body, key_override=key_override)
        if chat_id:
            line = res.get("normalized", {})
            symbol = line.get("symbol") or body.get("symbol")
            side = line.get("side") or body.get("side")
            entry = line.get("entry_price")
            last = line.get("last")
            sl   = line.get("sl_price")
            tp   = line.get("tp") or []
            tp_str = "/".join(str(int(t)) if isinstance(t,(int,float)) else str(t) for t in tp) if isinstance(tp, list) else "-"
            await _tg_send(chat_id,
                           f"✅ snapshot updated\n"
                           f"{symbol} {side}\n"
                           f"entry={entry} now={last} sl={sl} tp={tp_str}\n"
                           f"src=telegram • {time.strftime('%H:%M:%S', time.gmtime())}Z")
        return JSONResponse({"ok": True, "pushed": True, "result": res})
    except Exception as e:
        if chat_id: await _tg_send(chat_id, f"❌ failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
