# routes/ops_digest.py
from __future__ import annotations
import os, time, json, logging
from typing import Dict, Any, List, Tuple, Optional
from fastapi import APIRouter, Query, HTTPException

router = APIRouter(prefix="/ops", tags=["Ops"])

logger = logging.getLogger("algogpt.routes.ops_digest")

NS        = os.getenv("REDIS_NAMESPACE","ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL = os.getenv("REDIS_URL","").strip()

# Optional Redis
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

async def _redis():
    if not (aioredis and REDIS_URL):
        return None
    return aioredis.from_url(REDIS_URL, decode_responses=True)

# Telegram
BOT_TOKEN     = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
ADMIN_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID") or "").strip()

async def _send_telegram(text: str) -> Dict[str, Any]:
    if not (BOT_TOKEN and ADMIN_CHAT_ID):
        return {"ok": False, "skipped": True, "reason": "no_telegram_config"}
    try:
        import httpx
        payload = {
            "chat_id": int(ADMIN_CHAT_ID) if str(ADMIN_CHAT_ID).isdigit() else ADMIN_CHAT_ID,
            "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=12.0) as cli:
            r = await cli.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)
        try:
            return r.json()
        except Exception:
            return {"ok": False, "status": r.status_code, "body": r.text}
    except Exception as e:
        logger.warning({"event":"tg_send_failed","err":str(e)})
        return {"ok": False, "error": str(e)}

def _b(s: str) -> str:
    return f"<b>{s}</b>"

def _esc(s: Any) -> str:
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _format_digest(count: int, per_key: List[Tuple[str,int]], examples: List[Dict[str,Any]], hours: int) -> str:
    lines = []
    lines.append(f"📉 {_b('Expired-Approvals Digest')} · {_b(f'Last {hours}h')}")
    lines.append(f"Total expired: {_b(count)}")
    if per_key:
        lines.append("By symbol/side:")
        for k,c in per_key[:15]:
            lines.append(f" • {_esc(k)}: {_b(c)}")
    if examples:
        lines.append("Recent examples:")
        for e in examples[:10]:
            t = time.strftime("%H:%M", time.localtime(e.get('ts', 0)))
            lines.append(f" • {t} · {_esc(e.get('idem',''))} · {_esc(e.get('symbol',''))} {_esc(e.get('side',''))}")
    return "\n".join(lines)

async def _load_expired_last_hours(hours: int) -> List[Dict[str,Any]]:
    r = await _redis()
    if not r:
        return []
    key = f"{NS}:expired_log"
    # קח חלון אחרון של עד 1000 אירועים (למנוע עומס)
    raw_list = await r.lrange(key, 0, 999)
    out: List[Dict[str,Any]] = []
    if not raw_list:
        return out
    cutoff = time.time() - (hours * 3600)
    for raw in raw_list:
        try:
            item = json.loads(raw)
        except Exception:
            continue
        if float(item.get("ts") or 0) >= cutoff:
            out.append(item)
    return out

@router.get("/digest/expired", summary="Digest of auto-rejected approvals in the last N hours")
async def digest_expired(hours: int = Query(6, ge=1, le=72), send: int = Query(1)) -> Dict[str, Any]:
    """
    אוסף מה-Redis את לוג הכרטיסים שפגו, מסכם לפי symbol/side ושולח טלגרם (אם send=1, ברירת מחדל).
    דורש REDIS_URL לצורך איסוף.
    """
    items = await _load_expired_last_hours(hours)
    total = len(items)
    # אגרגציה: key = f"{sym} {side}"
    agg: Dict[str,int] = {}
    for it in items:
        key = f"{(it.get('symbol') or '').upper()} {(it.get('side') or '').upper()}".strip()
        if not key:
            key = "UNKNOWN"
        agg[key] = agg.get(key, 0) + 1
    per_key = sorted(agg.items(), key=lambda x: (-x[1], x[0]))
    # דוגמאות אחרונות (שמור על סדר כרונולוגי מהישן לחדש)
    examples = sorted(items, key=lambda x: x.get('ts', 0), reverse=True)

    res: Dict[str, Any] = {"ok": True, "hours": hours, "total": total, "breakdown": per_key, "examples": examples[:10]}
    if send:
        text = _format_digest(total, per_key, examples, hours)
        tg = await _send_telegram(text)
        res["telegram"] = tg
    return res
