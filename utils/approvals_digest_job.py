# utils/approvals_digest_job.py
from __future__ import annotations
import os, time, asyncio, logging, json

logger = logging.getLogger("algogpt.approvals.digest_job")

NS        = os.getenv("REDIS_NAMESPACE","ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL = os.getenv("REDIS_URL","").strip()

DIGEST_ENABLE        = os.getenv("DIGEST_EXPIRED_ENABLE","1").lower() in ("1","true","yes","on")
DIGEST_INTERVAL_H    = int(os.getenv("DIGEST_EXPIRED_INTERVAL_HOURS","6"))
DIGEST_HOURS_WINDOW  = int(os.getenv("DIGEST_EXPIRED_HOURS","6"))  # כמה שעות אחורה בסיכום
DIGEST_SEND          = os.getenv("DIGEST_EXPIRED_SEND","1").lower() in ("1","true","yes","on")

# Redis (optional)
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

async def _send_tg(text: str) -> dict:
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

def _esc(s: str) -> str:
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

async def _load_last_hours(hours: int):
    r = await _redis()
    if not r: return []
    key = f"{NS}:expired_log"
    raw = await r.lrange(key, 0, 999)  # חלון אחרון עד 1000 אירועים
    cutoff = time.time() - hours * 3600
    out = []
    for row in raw:
        try:
            it = json.loads(row)
        except Exception:
            continue
        if float(it.get("ts") or 0) >= cutoff:
            out.append(it)
    return out

def _build_digest(items, hours: int) -> str:
    total = len(items)
    agg = {}
    for it in items:
        k = f"{(it.get('symbol') or '').upper()} {(it.get('side') or '').upper()}".strip() or "UNKNOWN"
        agg[k] = agg.get(k, 0) + 1
    per_key = sorted(agg.items(), key=lambda x: (-x[1], x[0]))
    lines = []
    lines.append(f"📉 {_b('Expired-Approvals Digest (Auto)')} · {_b(f'Last {hours}h')}")
    lines.append(f"Total expired: {_b(total)}")
    if per_key:
        lines.append("By symbol/side:")
        for k,c in per_key[:15]:
            lines.append(f" • {_esc(k)}: {_b(c)}")
    return "\n".join(lines)

async def _take_rate_limit(interval_h: int) -> bool:
    r = await _redis()
    if not r: return False
    key = f"{NS}:digest_expired_lock"
    # אם יש lock, נחכה לסיבוב הבא
    ok = await r.set(key, str(int(time.time())), ex=max(300, int(interval_h*3600*0.9)), nx=True)
    return bool(ok)

async def digest_loop():
    if not DIGEST_ENABLE:
        logger.info({"event":"digest.disabled"}); return
    if not (aioredis and REDIS_URL):
        logger.info({"event":"digest.no_redis"}); return
    logger.info({"event":"digest.started","interval_h":DIGEST_INTERVAL_H,"hours_window":DIGEST_HOURS_WINDOW})
    while True:
        try:
            # קח lock ל־interval (מונע כפולים)
            got = await _take_rate_limit(DIGEST_INTERVAL_H)
            if got:
                items = await _load_last_hours(DIGEST_HOURS_WINDOW)
                if DIGEST_SEND:
                    msg = _build_digest(items, DIGEST_HOURS_WINDOW)
                    await _send_tg(msg)
                logger.info({"event":"digest.sent","items":len(items)})
            else:
                logger.debug({"event":"digest.skipped_rate_limited"})
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning({"event":"digest.loop_error","err":str(e)})
        await asyncio.sleep(max(60, DIGEST_INTERVAL_H * 3600))

def start_expired_digest_job() -> asyncio.Task:
    loop = asyncio.get_event_loop()
    return loop.create_task(digest_loop())
