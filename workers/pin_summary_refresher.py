# workers/pin_summary_refresher.py
from __future__ import annotations
import os, asyncio, json, time, hashlib, logging
from typing import Dict, Any, List, Optional, Set

import httpx

from utils.runtime_prefs import TelePrefs
from utils.hmac_utils import build_signed_outbound, generate_idempotency_key

LOGGER = logging.getLogger("pin_summary_refresher")
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO").upper())

ALERTS_ACTIVE_URL = os.getenv("ALERTS_ACTIVE_URL","http://127.0.0.1:8000/alerts/trades/active").strip()
ANALYSIS_URL      = os.getenv("ALERTS_ANALYSIS_URL","http://127.0.0.1:8000/alerts/analysis").strip()
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET","").strip()

PIN_REFRESH_SEC   = int(os.getenv("PIN_REFRESH_SEC","120"))     # כל כמה שניות לרענן
SUMMARY_LIMIT     = int(os.getenv("SUMMARY_LIMIT","15"))        # כמות פריטים בסיכום
TIMEZONE_NAME     = os.getenv("SUMMARY_TZ","Asia/Jerusalem")    # אזור זמן להצגה

tprefs = TelePrefs()

async def _get_active() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(ALERTS_ACTIVE_URL)
        r.raise_for_status()
        return r.json().get("items",[])

def _summary_sig(items: List[Dict[str, Any]]) -> str:
    try:
        payload = [
            {
                "id": str(it.get("trade_id")),
                "sym": it.get("symbol"),
                "side": it.get("side"),
                "now": float(it.get("current_price") or 0.0),
                "tp1": float(it.get("tp1") or 0.0),
                "sl":  float(it.get("sl")  or 0.0),
            }
            for it in items
        ]
        secret = WEBHOOK_HMAC_SECRET
        if secret:
            # שימוש ב-HMAC זהה לצד השרת; חתימה ידנית לצורך תקציר קצר
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",",":")).encode("utf-8")
            digest = hashlib.sha256((str(int(time.time()))+"\n").encode("utf-8") + raw).hexdigest()[:10]
            return f"🔐 sig: sha256={digest}"
        else:
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",",":")).encode("utf-8")
            short = hashlib.sha256(raw).hexdigest()[:10]
            return f"🔐 sig: sha256={short} (no-secret)"
    except Exception:
        return "🔐 sig: —"

def _build_summary_text(items: List[Dict[str, Any]]) -> str:
    # מיין לפי קרבה ל-TP1/SL
    def dist(it):
        try:
            nowp = float(it.get("current_price") or 0)
            tp1  = float(it.get("tp1")) if it.get("tp1") else None
            sl   = float(it.get("sl"))  if it.get("sl")  else None
        except Exception:
            return 9e9
        d1 = abs(nowp - tp1)/tp1 if (nowp and tp1) else 9e9
        ds = abs(nowp - sl)/sl   if (nowp and sl)  else 9e9
        return min(d1, ds)

    items = sorted(items, key=dist)[:SUMMARY_LIMIT]
    lines: List[str] = ["📋 *Active Summary*"]

    for it in items:
        sym  = it.get("symbol","")
        side = it.get("side","")
        try:
            nowp = float(it.get("current_price") or 0.0)
        except Exception:
            nowp = 0.0
        try:
            tp1 = float(it.get("tp1")) if it.get("tp1") else None
            sl  = float(it.get("sl"))  if it.get("sl")  else None
        except Exception:
            tp1, sl = None, None
        d1 = f"{abs(nowp-tp1)/tp1*100:.2f}%" if (nowp and tp1) else "—"
        ds = f"{abs(nowp-sl)/sl*100:.2f}%"   if (nowp and sl)  else "—"
        lines.append(f"- {sym} {side}: Now `{nowp:.6f}` | ΔTP1 {d1} | ΔSL {ds}")

    # חותמת זמן
    try:
        import zoneinfo, datetime as _dt
        tz = zoneinfo.ZoneInfo(TIMEZONE_NAME)
        stamp = _dt.datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    except Exception:
        stamp = time.strftime("%Y-%m-%d %H:%M")

    lines.append(f"\n🕒 {stamp} {TIMEZONE_NAME}")
    lines.append(_summary_sig(items))
    return "\n".join(lines)

async def _notify_edit(chat_id: int, message_id: int, text: str) -> Optional[Dict[str, Any]]:
    if not WEBHOOK_HMAC_SECRET:
        return None
    payload = {
        "chat_id": chat_id,
        "text": text,
        "edit_message_id": message_id
    }
    body, headers = build_signed_outbound(
        WEBHOOK_HMAC_SECRET, payload,
        idempotency_key=generate_idempotency_key(),
        extra_headers={"Content-Type":"application/json"},
    )
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(ANALYSIS_URL, content=body, headers=headers)
        try:
            r.raise_for_status()
            return r.json()
        except Exception:
            LOGGER.warning("edit failed for chat=%s msg=%s: %s", chat_id, message_id, r.text[:200])
            return None

async def _notify_send(chat_id: int, text: str) -> Optional[int]:
    if not WEBHOOK_HMAC_SECRET:
        return None
    payload = {
        "chat_id": chat_id,
        "text": text,
        "silent": True
    }
    body, headers = build_signed_outbound(
        WEBHOOK_HMAC_SECRET, payload,
        idempotency_key=generate_idempotency_key(),
        extra_headers={"Content-Type":"application/json"},
    )
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(ANALYSIS_URL, content=body, headers=headers)
        try:
            r.raise_for_status()
            data = r.json()
            # חפש message_id בתשובה
            mid = (data.get("result") or {}).get("message_id") or data.get("message_id")
            return int(mid) if mid else None
        except Exception:
            LOGGER.warning("send failed for chat=%s: %s", chat_id, r.text[:200])
            return None

async def step_once():
    pin_chats: Set[int] = await tprefs.list_pin_chats()
    if not pin_chats:
        return
    items = await _get_active()
    if not items:
        return
    text = _build_summary_text(items)

    for chat_id in pin_chats:
        pin_id = await tprefs.get_pin_message_id(chat_id)
        if pin_id:
            ok = await _notify_edit(chat_id, pin_id, text)
            if not ok:
                # ייתכן שההודעה נמחקה; נשלח חדשה ונעדכן id
                new_id = await _notify_send(chat_id, text)
                if new_id:
                    await tprefs.set_pin_message_id(chat_id, new_id)
        else:
            # אין pin_id שמור — נשלח אחת ונשמור
            new_id = await _notify_send(chat_id, text)
            if new_id:
                await tprefs.set_pin_message_id(chat_id, new_id)

async def main():
    while True:
        try:
            await step_once()
        except Exception as e:
            LOGGER.exception("pin refresher error: %s", e)
        await asyncio.sleep(PIN_REFRESH_SEC)

if __name__ == "__main__":
    asyncio.run(main())
