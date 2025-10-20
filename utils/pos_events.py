# utils/pos_events.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, time, asyncio
from typing import Any, Dict, Optional

import httpx
from contextlib import suppress

from utils.redis_helper import get_redis  # מצפה לפונקציה שמחזירה redis.asyncio client

# ====== Config (ENV) ======
_POS_EVENTS_KEY   = os.getenv("POS_EVENTS_KEY", "pos:events")
_POS_EVENTS_CHAN  = os.getenv("POS_EVENTS_CHAN", "pos:events:chan")
_POS_EVENTS_MAX   = int(os.getenv("POS_EVENTS_MAX", "500") or 500)

# הודעות טלגרם — ברירת־מחדל: מופעל
_TELEGRAM_ENABLE  = os.getenv("POS_EVENTS_TELEGRAM_ENABLE", "1").lower() in ("1","true","yes","on")
# רמת משלוח: all / important / none
_TELEGRAM_LEVEL   = (os.getenv("POS_EVENTS_TELEGRAM_LEVEL", "important") or "important").lower()
_TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")  # כבר קיים אצלך ב-main
_TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID")

# אימות “משתיק” את המודול אם אין מינימום תלות
def _tg_ready() -> bool:
    return bool(_TELEGRAM_ENABLE and _TELEGRAM_TOKEN and _TELEGRAM_CHAT_ID)

def _should_tg(op: str) -> bool:
    if not _tg_ready(): return False
    if _TELEGRAM_LEVEL == "none": return False
    if _TELEGRAM_LEVEL == "all": return True
    # important: רק אירועים מהותיים
    return op in ("sl_move", "trail_move", "tp_hit", "be_move")

def _fmt_num(x: Any, d: int = 4) -> str:
    try:
        return f"{float(x):.{d}f}"
    except Exception:
        return str(x)

def _render_tg_text(e: Dict[str, Any]) -> str:
    # הודעה קומפקטית לטלגרם (HTML)
    sym = e.get("sym","-")
    op  = e.get("op","event")
    ts  = int(e.get("ts", time.time()))
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts)) + "Z"

    if op == "trail_move":
        return (
            f"🧭 <b>Trail move</b> · <code>{sym}</code>\n"
            f"• { _fmt_num(e.get('from')) } → <b>{ _fmt_num(e.get('to')) }</b>\n"
            f"<i>{when}</i>"
        )
    if op == "sl_move":
        return (
            f"🛡 <b>SL move</b> · <code>{sym}</code>\n"
            f"• { _fmt_num(e.get('from')) } → <b>{ _fmt_num(e.get('to')) }</b>\n"
            f"<i>{when}</i>"
        )
    if op == "be_arm":
        return (
            f"⚙️ <b>BE armed</b> · <code>{sym}</code>\n"
            f"• @ { _fmt_num(e.get('bps'), 2) } bps\n"
            f"<i>{when}</i>"
        )
    if op == "be_move":
        return (
            f"⚙️ <b>BE move</b> · <code>{sym}</code>\n"
            f"• { _fmt_num(e.get('from_bps'), 2) } → <b>{ _fmt_num(e.get('to_bps'), 2) }</b> bps\n"
            f"<i>{when}</i>"
        )
    if op == "tp_place":
        idx = f" #{int(e['idx'])}" if e.get("idx") is not None else ""
        return (
            f"🎯 <b>TP place{idx}</b> · <code>{sym}</code>\n"
            f"• price { _fmt_num(e.get('price')) } · qty { _fmt_num(e.get('qty')) }\n"
            f"<i>{when}</i>"
        )
    if op == "tp_hit":
        idx = f" #{int(e['idx'])}" if e.get("idx") is not None else ""
        return (
            f"✅ <b>TP hit{idx}</b> · <code>{sym}</code>\n"
            f"• price { _fmt_num(e.get('price')) } · qty { _fmt_num(e.get('qty')) }\n"
            f"<i>{when}</i>"
        )
    if op == "note":
        return (
            f"📝 <b>Note</b> · <code>{sym}</code>\n"
            f"• { e.get('msg','') }\n"
            f"<i>{when}</i>"
        )
    # fallback
    body = json.dumps({k:v for k,v in e.items() if k not in ("ts",)}, ensure_ascii=False)
    return f"ℹ️ <b>{op}</b> · <code>{sym}</code>\n{body}\n<i>{when}</i>"

async def _send_tg(text: str) -> Dict[str, Any]:
    if not _tg_ready():
        return {"ok": True, "skipped": True, "reason": "telegram_not_ready"}
    try:
        cid: Any = int(_TELEGRAM_CHAT_ID) if str(_TELEGRAM_CHAT_ID).isdigit() else _TELEGRAM_CHAT_ID
    except Exception:
        cid = _TELEGRAM_CHAT_ID
    payload = {"chat_id": cid, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as cli:
            r = await cli.post(f"https://api.telegram.org/bot{_TELEGRAM_TOKEN}/sendMessage", json=payload)
            ok = False
            with suppress(Exception):
                ok = (r.status_code == 200) and (r.json().get("ok") is True)
            return {"ok": ok, "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def emit(sym: str, op: str, **fields: Any) -> Dict[str, Any]:
    """
    פרסום אירוע:
      1) LPUSH לאחסון קצר ב-Redis (עד POS_EVENTS_MAX)
      2) PUBLISH לערוץ POS_EVENTS_CHAN
      3) הודעת טלגרם (אופציונלי, לפי רמה)
    מחזיר את האירוע שנשלח.
    """
    evt: Dict[str, Any] = {"sym": sym.upper(), "op": op, "ts": int(time.time()), **fields}
    r = await get_redis()
    if r:
        try:
            pipe = r.pipeline()
            pipe.lpush(_POS_EVENTS_KEY, json.dumps(evt, ensure_ascii=False, separators=(",",":")))
            pipe.ltrim(_POS_EVENTS_KEY, 0, max(0, _POS_EVENTS_MAX - 1))
            pipe.publish(_POS_EVENTS_CHAN, json.dumps(evt, ensure_ascii=False, separators=(",",":")))
            await pipe.execute()
        except Exception:
            # לא מפילים את היישום — רק מדלגים על אחסון
            pass

    if _should_tg(op):
        # fire-and-forget (לא לעכב את הזרימה העסקית)
        asyncio.create_task(_send_tg(_render_tg_text(evt)))

    return evt

# עטיפה נוחה לסביבה סינכרונית
def emit_sync(sym: str, op: str, **fields: Any) -> Dict[str, Any]:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # בתוך event-loop: משגרים משימה
        asyncio.create_task(emit(sym, op, **fields))
        return {"sym": sym.upper(), "op": op, "queued": True}
    # אין loop רץ: יוצרים זמני
    return asyncio.run(emit(sym, op, **fields))

