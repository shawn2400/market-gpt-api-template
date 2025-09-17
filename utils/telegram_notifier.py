# utils/telegram_notifier.py
from __future__ import annotations

import os, time, asyncio, logging, hashlib, hmac, json
from typing import Any, Dict, Optional, List, Tuple
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, quote

# ---- TZ (Asia/Jerusalem) ----
try:
    from zoneinfo import ZoneInfo
    _TZ_IL = ZoneInfo("Asia/Jerusalem")
except Exception:
    _TZ_IL = timezone(timedelta(hours=3))  # Fallback UTC+3

logger = logging.getLogger("algogpt.tg")

# ===================== Core Telegram Config =====================
BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID        = int(os.getenv("TELEGRAM_CHAT_ID", os.getenv("TELEGRAM_APPROVAL_CHAT_ID", "0")) or 0)
API_BASE       = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
PUBLIC_HOST    = os.getenv("PUBLIC_HOST", "").strip().rstrip("/")

# ===================== Explain flags =====================
_EXPLAIN_ON              = os.getenv("OPS_EXPLAIN_TRADE_TELEGRAM", "1").lower() in ("1","true","yes","on")
EXPLAIN_COOLDOWN_SEC     = int(os.getenv("OPS_EXPLAIN_COOLDOWN_SEC", "45"))
EXPLAIN_MAX_PER_MIN      = int(os.getenv("OPS_EXPLAIN_MAX_PER_MIN", "6"))
EXPLAIN_MIN_SCORE        = float(os.getenv("OPS_EXPLAIN_MIN_SCORE", "0"))

# ===================== Bundling / Rate-limit =====================
BUNDLE_ENABLE            = os.getenv("OPS_ALERT_BUNDLING", "1").lower() in ("1","true","yes","on")
BUNDLE_WINDOW_SEC        = int(os.getenv("OPS_ALERT_BUNDLE_WINDOW_SEC", "30"))
BUNDLE_MAX_ITEMS         = int(os.getenv("OPS_ALERT_BUNDLE_MAX_ITEMS", "12"))
BUNDLE_TITLE             = os.getenv("OPS_ALERT_BUNDLE_TITLE", "🔔 Ops Alerts")

SEND_MAX_PER_MIN         = int(os.getenv("TG_SEND_MAX_PER_MIN", "25"))
DEDUP_TTL_SEC            = int(os.getenv("TG_DEDUP_TTL_SEC", "20"))

_last_explain_ts: float = 0.0
_win_start: float = 0.0
_sent_in_win: int = 0

_rl_win_start: float = 0.0
_rl_sent_in_win: int = 0
_dedup_map: Dict[str, float] = {}

_bundle_items: List[str] = []
_bundle_task: Optional[asyncio.Task] = None
_bundle_lock = asyncio.Lock()

# ===================== Auto-Approval & Digest Policy =====================
def _parse_list_env(name: str, default_csv: str) -> List[str]:
    return [x.strip().lower() for x in os.getenv(name, default_csv).split(",") if x.strip()]

OPS_APPROVAL_STRICT           = os.getenv("OPS_APPROVAL_STRICT", "1").lower() in ("1","true","yes","on")
OPS_MANUAL_MIN_CRS            = float(os.getenv("OPS_MANUAL_MIN_CRS", "8"))
OPS_MANUAL_SENSITIVE_LEVELS   = set(_parse_list_env("OPS_MANUAL_SENSITIVE_LEVELS", "high,critical"))
OPS_MANUAL_TOUCHES            = set(_parse_list_env("OPS_MANUAL_TOUCHES", "trading,env"))

OPS_AUTO_APPROVE_NON_SENSITIVE = os.getenv("OPS_AUTO_APPROVE_NON_SENSITIVE", "1").lower() in ("1","true","yes","on")
OPS_AUTO_CRS_MAX               = int(os.getenv("OPS_AUTO_CRS_MAX", "6"))
OPS_APPROVAL_BASE              = os.getenv("OPS_APPROVAL_BASE", PUBLIC_HOST).rstrip("/")
WEBHOOK_HMAC_SECRET            = os.getenv("WEBHOOK_HMAC_SECRET","").strip()

OPS_DIGEST_ENABLE              = os.getenv("OPS_DIGEST_ENABLE","1").lower() in ("1","true","yes","on")
OPS_DIGEST_INTERVAL_HOURS      = max(3, min(5, int(os.getenv("OPS_DIGEST_INTERVAL_HOURS","3"))))  # clamp 3..5
OPS_EOD_ENABLE                 = os.getenv("OPS_EOD_ENABLE","1").lower() in ("1","true","yes","on")
OPS_EOD_HOUR_IL                = int(os.getenv("OPS_EOD_HOUR_IL","23"))
OPS_EOD_MINUTE_IL              = int(os.getenv("OPS_EOD_MINUTE_IL","55"))

OPS_APPROVAL_EMOJI             = os.getenv("OPS_APPROVAL_EMOJI","1").lower() in ("1","true","yes","on")

# 🆕 שפת הודעות: mix | he | en
OPS_APPROVAL_LANG              = os.getenv("OPS_APPROVAL_LANG", "mix").strip().lower()
if OPS_APPROVAL_LANG not in ("mix","he","en"):
    OPS_APPROVAL_LANG = "mix"

# 🆕 האם להוסיף action=approve/reject ל-URLs (דיפולט 0 למקסימום תאימות)
OPS_REQUIRE_ACTION_PARAM       = os.getenv("OPS_REQUIRE_ACTION_PARAM","0").lower() in ("1","true","yes","on")

# Optional Redis (לרישום אירועים לדיג'סט). נופל לקובץ אם אין Redis.
_redis = None
try:
    _redis_url = os.getenv("REDIS_URL","").strip()
    if _redis_url:
        import redis.asyncio as aioredis
        _redis = aioredis.from_url(_redis_url, decode_responses=True)
except Exception as _e:
    logger.debug({"event":"redis.disabled","reason":str(_e)})

_changes_file = os.getenv("OPS_CHANGES_FILE", "/tmp/ops_changes.jsonl")

# ===================== Helpers (Rate-limit / Dedup) =====================
def set_explain_enabled(v: bool) -> None:
    global _EXPLAIN_ON
    _EXPLAIN_ON = bool(v)

def get_explain_enabled() -> bool:
    return bool(_EXPLAIN_ON)

def _now() -> float:
    return time.time()

def _now_dt_utc() -> datetime:
    return datetime.now(timezone.utc)

def _fmt_il(ts: float | int | None = None) -> str:
    dt = datetime.fromtimestamp(ts or _now(), tz=timezone.utc).astimezone(_TZ_IL)
    return dt.strftime("%Y-%m-%d %H:%M:%S IL")

def _rl_tick() -> None:
    global _rl_win_start, _rl_sent_in_win
    now = _now()
    if _rl_win_start == 0.0 or (now - _rl_win_start) >= 60.0:
        _rl_win_start = now
        _rl_sent_in_win = 0

def _rl_allow() -> bool:
    _rl_tick()
    global _rl_sent_in_win
    if _rl_sent_in_win >= max(1, SEND_MAX_PER_MIN):
        return False
    _rl_sent_in_win += 1
    return True

def _dedup_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()

def _dedup_allow(text: str) -> bool:
    now = _now()
    key = _dedup_key(text)
    ts = _dedup_map.get(key, 0.0)
    if now - ts <= DEDUP_TTL_SEC:
        return False
    _dedup_map[key] = now
    if len(_dedup_map) > 1024:
        for k, v in list(_dedup_map.items())[:128]:
            if now - v > DEDUP_TTL_SEC * 3:
                _dedup_map.pop(k, None)
    return True

# ===================== Low-level send =====================
async def _http_send(text: str, chat_id: Optional[int] = None) -> None:
    if not BOT_TOKEN or (chat_id is None and CHAT_ID == 0):
        logger.debug({"event":"tg.skip_send","reason":"missing_token_or_chat"})
        return
    if not _rl_allow():
        logger.debug({"event":"tg.rate_limited","drop":True})
        return
    if not _dedup_allow(text):
        logger.debug({"event":"tg.dup_suppressed"})
        return
    cid = chat_id if chat_id is not None else CHAT_ID
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(f"{API_BASE}/sendMessage", data={
                "chat_id": cid,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
    except Exception as e:
        logger.warning({"event":"tg.send_failed","error":str(e)})

async def _http_send_with_markup(text: str, reply_markup: Dict[str, Any], chat_id: Optional[int] = None) -> None:
    if not BOT_TOKEN or (chat_id is None and CHAT_ID == 0):
        logger.debug({"event":"tg.skip_send","reason":"missing_token_or_chat"})
        return
    if not _rl_allow():
        logger.debug({"event":"tg.rate_limited","drop":True})
        return
    keytext = text + json.dumps(reply_markup, sort_keys=True, ensure_ascii=False)
    if not _dedup_allow(keytext):
        logger.debug({"event":"tg.dup_suppressed"})
        return
    cid = chat_id if chat_id is not None else CHAT_ID
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(f"{API_BASE}/sendMessage", json={
                "chat_id": cid,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": reply_markup,
            })
    except Exception as e:
        logger.warning({"event":"tg.send_failed","error":str(e)})

async def _tg_send(text: str, chat_id: Optional[int] = None) -> None:
    try:
        await _http_send(text, chat_id=chat_id)
    except RuntimeError:
        try:
            asyncio.get_event_loop().create_task(_http_send(text, chat_id=chat_id))
        except Exception:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_http_send(text, chat_id=chat_id))
            loop.close()

async def _tg_send_with_markup(text: str, reply_markup: Dict[str, Any], chat_id: Optional[int] = None) -> None:
    try:
        await _http_send_with_markup(text, reply_markup, chat_id=chat_id)
    except RuntimeError:
        try:
            asyncio.get_event_loop().create_task(_http_send_with_markup(text, reply_markup, chat_id=chat_id))
        except Exception:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_http_send_with_markup(text, reply_markup, chat_id=chat_id))
            loop.close()

# ===================== Bundling =====================
def _win_tick() -> None:
    global _win_start, _sent_in_win
    now = _now()
    if _win_start == 0.0 or (now - _win_start) >= 60.0:
        _win_start = now
        _sent_in_win = 0

async def _bundle_flush() -> None:
    global _bundle_items
    async with _bundle_lock:
        if not _bundle_items:
            return
        items = _bundle_items[:BUNDLE_MAX_ITEMS]
        more = len(_bundle_items) - len(items)
        _bundle_items = []
    lines = [f"{BUNDLE_TITLE}", ""]
    for it in items:
        lines.append(f"• {it}")
    if more > 0:
        lines.append(f"\n…and {more} more")
    await _tg_send("\n".join(lines))

async def _bundle_schedule_flush() -> None:
    global _bundle_task
    async with _bundle_lock:
        if _bundle_task and not _bundle_task.done():
            return
        async def _delayed():
            try:
                await asyncio.sleep(BUNDLE_WINDOW_SEC)
                await _bundle_flush()
            except Exception as e:
                logger.debug({"event":"bundle.flush.err","err":str(e)})
        _bundle_task = asyncio.create_task(_delayed())

async def _bundle_add(msg: str) -> None:
    global _bundle_items
    async with _bundle_lock:
        _bundle_items.append(msg)
    await _bundle_schedule_flush()

# ===================== Public Ops Notifications =====================
async def notify_no_trades() -> None:
    return None

async def notify_scan_error(reason: str) -> None:
    txt = f"⚠️ <b>Scan error</b>\n<code>{reason}</code>"
    if BUNDLE_ENABLE:
        await _bundle_add(txt.replace("\n", " | "))
    else:
        await _tg_send(txt)

async def notify_ops_alert(msg: str) -> None:
    txt = f"🛠 {msg}"
    if BUNDLE_ENABLE:
        await _bundle_add(txt)
    else:
        await _tg_send(txt)

async def notify_explain_trade(plan: Dict[str, Any]) -> None:
    if not _EXPLAIN_ON:
        return
    if float(plan.get("score", 0.0)) < EXPLAIN_MIN_SCORE:
        return
    global _last_explain_ts, _sent_in_win
    _win_tick()
    now = _now()
    if _last_explain_ts and (now - _last_explain_ts) < EXPLAIN_COOLDOWN_SEC:
        return
    if _sent_in_win >= max(1, EXPLAIN_MAX_PER_MIN):
        return

    sym   = str(plan.get("symbol","")).upper()
    side  = str(plan.get("side","")).upper()
    lev   = int(plan.get("leverage", 0) or 0)
    entry = float(plan.get("entry", 0.0) or plan.get("entry_price", 0.0) or 0.0)
    sl    = float(plan.get("sl", 0.0) or plan.get("sl_price", 0.0) or 0.0)
    tp    = float(plan.get("tp", 0.0) or 0.0)
    adx   = float(plan.get("adx", plan.get("dyn", {}).get("adx", 0.0)) or 0.0)
    atr   = float(plan.get("atr", plan.get("dyn", {}).get("atr_pct", 0.0)) or 0.0)
    score = float(plan.get("score", 0.0) or 0.0)
    ema21 = plan.get("ema_21")
    ema50 = plan.get("ema_50")
    macdh = plan.get("macd_hist")
    rsi   = plan.get("rsi")

    trend_ok = "✓" if (ema21 and ema50 and ((float(ema21) > float(ema50) and side in ("LONG","BUY")) or (float(ema21) < float(ema50) and side in ("SHORT","SELL")))) else "✗"
    macd_ok  = "✓" if (macdh is not None and ((side in ("LONG","BUY") and float(macdh)>0) or (side in ("SHORT","SELL") and float(macdh)<0))) else "✗"

    lines = [f"⚙️ <b>Explain Trade</b>", f"<b>{sym}</b> · <b>{side}</b> · lev=<b>{lev}</b>"]
    if ema21 and ema50: lines.append(f"EMA21{'>' if float(ema21)>float(ema50) else '<'}EMA50 {trend_ok}")
    if macdh is not None: lines.append(f"MACD hist {float(macdh):+.4f} {macd_ok}")
    if adx or atr:
        try:
            lines.append(f"ADX {adx:.0f} | ATR% {float(atr):.2f}" if float(atr) < 10 else f"ADX {adx:.0f} | ATR {float(atr):.4f}")
        except Exception:
            lines.append(f"ADX {adx:.0f}")
    if rsi is not None:
        try:
            lines.append(f"RSI {float(rsi):.1f}")
        except Exception:
            pass
    lines.append(f"Quality Score: <b>{score:.2f}/10</b>")
    if entry and (sl or tp):
        try:
            lines.append(f"Entry {entry:.4f} | SL {sl:.4f} | TP {tp:.4f}")
        except Exception:
            lines.append(f"Entry {entry} | SL {sl} | TP {tp}")

    await _tg_send("\n".join(lines))
    _last_explain_ts = now
    _sent_in_win += 1

async def notify_sl_tp_update(symbol: str, side: str, kind: str, value: Any) -> None:
    try:
        val = f"{float(value):.4f}" if isinstance(value, (int, float)) or (isinstance(value, str) and value.replace('.','',1).isdigit()) else str(value)
    except Exception:
        val = str(value)
    await _tg_send(f"🔧 <b>{symbol}</b> {side} · {kind.upper()} → <code>{val}</code>")

async def notify_info(text: str) -> None:  await _tg_send(f"ℹ️ {text}")
async def notify_error(text: str) -> None: await _tg_send(f"🚨 {text}")
async def notify_heartbeat() -> None:      await _tg_send("🫀 Heartbeat OK")

async def notify_daily_summary(summary: Dict[str, Any]) -> None:
    pnl = summary.get("pnl", 0.0)
    t   = summary.get("time", "")
    n   = len(summary.get("trades") or [])
    try:
        pnl_fmt = f"{float(pnl):.2f}"
    except Exception:
        pnl_fmt = str(pnl)
    await _tg_send(f"📘 Daily Summary {t}\nPnL: <b>{pnl_fmt}</b> USDT · trades={n}")

# ===================== Webhook Registration =====================
async def register_webhook() -> bool:
    public_host = PUBLIC_HOST
    secret_token = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not BOT_TOKEN or not public_host or not secret_token:
        return False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(f"{API_BASE}/setWebhook", data={
                "url": f"{public_host}/telegram/webhook",
                "secret_token": secret_token,
                "drop_pending_updates": "true",
                "max_connections": "40",
            })
            return r.status_code == 200 and r.json().get("ok", False)
    except Exception as e:
        logger.warning({"event": "register_webhook_failed", "error": str(e)})
        return False

# ===================== Formatting Helpers =====================
def _em(emoji: str, text: str) -> str:
    return f"{emoji} {text}" if OPS_APPROVAL_EMOJI else text

def _fmt_pct(v: float | int | None) -> str:
    try:
        return f"{float(v):.0f}%"
    except Exception:
        return "—"

def _fmt_int(v: int | float | None) -> str:
    try:
        return str(int(float(v)))
    except Exception:
        return "—"

def _ts_pair(iso_utc: Optional[str]) -> Tuple[str, str]:
    try:
        dt = datetime.fromisoformat(str(iso_utc).replace("Z","+00:00")) if iso_utc else _now_dt_utc()
    except Exception:
        dt = _now_dt_utc()
    utc_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    il_dt   = dt.astimezone(_TZ_IL)
    il_str  = il_dt.strftime("%Y-%m-%d %H:%M:%S IL")
    return il_str, utc_str

def _sign(ticket_id: str, expires_epoch: int) -> str:
    msg = f"{ticket_id}:{expires_epoch}".encode("utf-8")
    secret = (os.getenv("WEBHOOK_HMAC_SECRET","") or WEBHOOK_HMAC_SECRET).encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest() if secret else ""

def _ensure_urls(change: Dict[str, Any]) -> Dict[str, str]:
    tid = change.get("ticket_id", "")
    expires = int(change.get("ops_expires") or (_now() + int(change.get("ttl_sec", 600))))
    approve_url = change.get("approve_url")
    reject_url  = change.get("reject_url")
    ticket_url  = change.get("ticket_url")

    if OPS_APPROVAL_BASE and tid and not (approve_url and reject_url and ticket_url):
        sig = _sign(tid, int(expires)) if WEBHOOK_HMAC_SECRET else ""
        q = {"ticket_id": tid, "expires": int(expires)}
        if sig: q["sig"] = sig
        qs = urlencode(q)
        if OPS_REQUIRE_ACTION_PARAM:
            approve_url = approve_url or f"{OPS_APPROVAL_BASE}/ops/approve?{qs}&action=approve"
            reject_url  = reject_url  or f"{OPS_APPROVAL_BASE}/ops/reject?{qs}&action=reject"
        else:
            approve_url = approve_url or f"{OPS_APPROVAL_BASE}/ops/approve?{qs}"
            reject_url  = reject_url  or f"{OPS_APPROVAL_BASE}/ops/reject?{qs}"
        ticket_url  = ticket_url  or f"{OPS_APPROVAL_BASE}/ops/ticket/{quote(str(tid))}"

    return {"approve": approve_url or "", "reject": reject_url or "", "ticket": ticket_url or ""}

# ===================== HE / EN / MIX Formatting (Change Tickets) =====================
def _format_change_he(change: Dict[str, Any]) -> str:
    tid = str(change.get("ticket_id","—"))
    ttl = int(change.get("ttl_sec", 600))
    crs = change.get("crs", "—")
    sensitive = bool(change.get("sensitive", False))
    two_man   = bool(change.get("two_man", False))
    version   = change.get("version", "—")
    plan      = change.get("plan", "—")

    budget   = change.get("budget") or {}
    dollars  = budget.get("dollars_max", 0.0)
    api_max  = budget.get("api_calls_max", 0)
    tokens   = budget.get("ai_tokens_max", 0)

    impact   = change.get("impact") or {}
    cpu_pct  = impact.get("cpu_pct", None)
    mem_pct  = impact.get("mem_pct", None)
    api_rate = impact.get("api_per_min", None)

    changes  = change.get("changes") or []
    touches  = change.get("touches") or {}
    canary   = bool(change.get("canary", True))
    rollback = bool(change.get("rollback", True))
    created_at = change.get("created_at")

    il_ts, utc_ts = _ts_pair(created_at)

    try:
        dollars_fmt = f"{float(dollars):.2f}"
    except Exception:
        dollars_fmt = str(dollars)

    t_trd = bool(touches.get("trading", False))
    t_alr = bool(touches.get("alerts", False))
    t_env = bool(touches.get("env", False))

    lines: List[str] = []
    lines.append(f"<b>{_em('🕒','זמן')}</b>: {il_ts} | {utc_ts}")
    lines.append(f"<b>{_em('✅','דרוש אישור שינוי')}</b> (Change Approval)")
    lines.append(f"<b>ID</b>: <code>{tid}</code>")
    lines.append(f"<b>Two-man</b>: {'ON' if two_man else 'OFF'} | <b>TTL</b>: {ttl}s")
    lines.append(f"<b>CRS</b>: {crs}/10 | <b>Sensitive</b>: {'True' if sensitive else 'False'}")
    lines.append(f"<b>Version</b>: <code>{version}</code>")
    lines.append(f"{_em('📝','תכנית')} — {plan}")
    lines.append("— — —")
    lines.append(f"{_em('🖥️','השפעת עומס (משוער)')}: CPU {_fmt_pct(cpu_pct)}, Mem {_fmt_pct(mem_pct)}, API/דקה {_fmt_int(api_rate)}")
    lines.append(f"{_em('💰','עלות (תקרה)')}: ${dollars_fmt} | טוקני AI: {_fmt_int(tokens)} | קריאות API: {_fmt_int(api_max)}")
    lines.append(f"{_em('⚙️','שינויים')}: " + (", ".join(changes) if changes else "—"))
    lines.append(f"{_em('🔌','נגיעה ברכיבים')}: Trading={'כן' if t_trd else 'לא'}, Alerts={'כן' if t_alr else 'לא'}, ENV={'כן' if t_env else 'לא'}")
    lines.append(f"{_em('🛡️','בטיחות')}: Canary={'ON' if canary else 'OFF'} | Rollback={'ON' if rollback else 'OFF'}")
    lines.append(_em("ℹ️", "לחיצה על \"אשר\" תפעיל Preflight → Canary → Promote → Post-verify עם ביטול/Rollback אוטומטי אם יש סטייה."))
    return "\n".join(lines)

def _format_change_en(change: Dict[str, Any]) -> str:
    tid = str(change.get("ticket_id","—"))
    ttl = int(change.get("ttl_sec", 600))
    crs = change.get("crs", "—")
    sensitive = bool(change.get("sensitive", False))
    two_man   = bool(change.get("two_man", False))
    version   = change.get("version", "—")
    plan      = change.get("plan", "—")

    budget   = change.get("budget") or {}
    dollars  = budget.get("dollars_max", 0.0)
    api_max  = budget.get("api_calls_max", 0)
    tokens   = budget.get("ai_tokens_max", 0)

    impact   = change.get("impact") or {}
    cpu_pct  = impact.get("cpu_pct", None)
    mem_pct  = impact.get("mem_pct", None)
    api_rate = impact.get("api_per_min", None)

    changes  = change.get("changes") or []
    touches  = change.get("touches") or {}
    canary   = bool(change.get("canary", True))
    rollback = bool(change.get("rollback", True))
    created_at = change.get("created_at")

    il_ts, utc_ts = _ts_pair(created_at)
    try:
        dollars_fmt = f"{float(dollars):.2f}"
    except Exception:
        dollars_fmt = str(dollars)

    t_trd = bool(touches.get("trading", False))
    t_alr = bool(touches.get("alerts", False))
    t_env = bool(touches.get("env", False))

    lines: List[str] = []
    lines.append(f"<b>{_em('🕒','Time')}</b>: {il_ts} | {utc_ts}")
    lines.append(f"<b>{_em('✅','Change Approval Required')}</b>")
    lines.append(f"<b>ID</b>: <code>{tid}</code>")
    lines.append(f"<b>Two-man</b>: {'ON' if two_man else 'OFF'} | <b>TTL</b>: {ttl}s")
    lines.append(f"<b>CRS</b>: {crs}/10 | <b>Sensitive</b>: {'True' if sensitive else 'False'}")
    lines.append(f"<b>Version</b>: <code>{version}</code>")
    lines.append(f"{_em('📝','Plan')} — {plan}")
    lines.append("— — —")
    lines.append(f"{_em('🖥️','Estimated Load Impact')}: CPU {_fmt_pct(cpu_pct)}, Mem {_fmt_pct(mem_pct)}, API/min {_fmt_int(api_rate)}")
    lines.append(f"{_em('💰','Cost Cap')}: ${dollars_fmt} | AI tokens: {_fmt_int(tokens)} | API calls: {_fmt_int(api_max)}")
    lines.append(f"{_em('⚙️','Changes')}: " + (", ".join(changes) if changes else "—"))
    lines.append(f"{_em('🔌','Touches')}: Trading={'Yes' if t_trd else 'No'}, Alerts={'Yes' if t_alr else 'No'}, ENV={'Yes' if t_env else 'No'}")
    lines.append(f"{_em('🛡️','Safety')}: Canary={'ON' if canary else 'OFF'} | Rollback={'ON' if rollback else 'OFF'}")
    lines.append(_em("ℹ️", 'Press "Approve" to run Preflight → Canary → Promote → Post-verify with auto rollback on deviation.'))
    return "\n".join(lines)

def _format_change_mixed(change: Dict[str, Any]) -> str:
    he = _format_change_he(change)
    en = _format_change_en(change)
    return he + "\n\n" + en

def format_change_approval_he(change: Dict[str, Any]) -> str:
    """Back-compat name; respects OPS_APPROVAL_LANG."""
    if OPS_APPROVAL_LANG == "he":
        return _format_change_he(change)
    if OPS_APPROVAL_LANG == "en":
        return _format_change_en(change)
    return _format_change_mixed(change)

# ===================== Send Change Approval =====================
async def send_change_approval_he(change: Dict[str, Any], chat_id: Optional[int] = None) -> Dict[str, Any] | None:
    """Back-compat name; sends Mix/HE/EN per OPS_APPROVAL_LANG."""
    if not BOT_TOKEN or not API_BASE:
        logger.debug({"event":"tg.skip_send","reason":"missing_token_or_api"})
        return None
    urls = _ensure_urls(change)
    text = format_change_approval_he(change)

    kb_rows: list[list[dict[str,str]]] = []
    row1 = []
    if urls.get("approve"):
        row1.append({"text": "✅ אשר / Approve", "url": urls["approve"]})
    if urls.get("reject"):
        row1.append({"text": "❌ דחה / Reject", "url": urls["reject"]})
    if row1: kb_rows.append(row1)
    if urls.get("ticket"):
        kb_rows.append([{"text": "🧾 פרטי הטיקט / Ticket", "url": urls["ticket"]}])

    reply_markup = {"inline_keyboard": kb_rows}
    try:
        await _tg_send_with_markup(text, reply_markup, chat_id=chat_id)
        return {"ok": True}
    except Exception as e:
        logger.warning({"event":"tg.approval_send_failed","error":str(e)})
        return {"ok": False, "error": str(e)}

# ===================== Trade-specific notifications (RICH) =====================
from typing import Sequence

def _try_get_live_price(symbol: str) -> Optional[float]:
    # ננסה להשיג מחיר נוכחי מהקוד שלך; אם לא קיים/נכשל—נחזיר None
    try:
        from utils.binance_client import get_price  # קיים אצלך
        p = get_price(symbol.upper())
        return float(p) if p else None
    except Exception:
        return None

def _fmt_usd(v: Any) -> str:
    try:
        return f"${float(v):.2f}"
    except Exception:
        return "—"

def _fmt_num(v: Any, prec: int = 4) -> str:
    try:
        return f"{float(v):.{prec}f}"
    except Exception:
        return str(v) if v is not None else "—"

def _fmt_pct_prob(p: Any) -> str:
    try:
        p = float(p)
        if p <= 1.0:  # תומך גם ב-0..1 וגם ב-0..100
            p *= 100.0
        return f"{p:.0f}%"
    except Exception:
        return "—"

def _fmt_eta(sec: Any) -> str:
    try:
        s = int(float(sec))
        if s < 60:
            return f"~{s}s"
        m, s = divmod(s, 60)
        if m < 60:
            return f"~{m}m{s:02d}s"
        h, m = divmod(m, 60)
        return f"~{h}h {m}m"
    except Exception:
        return "—"

def _tp_legs_to_lines(tp_legs: Optional[Sequence[Dict[str, Any]]],
                      eta: Dict[str, Any] | None = None,
                      probs: Dict[str, Any] | None = None) -> list[str]:
    lines: list[str] = []
    if not tp_legs:
        return [f"🎯 TP: —"]
    for i, leg in enumerate(tp_legs, start=1):
        px = leg.get("stopPrice") or leg.get("price")
        qty = leg.get("qty") or leg.get("size") or leg.get("split")
        leg_eta = None
        if eta:
            leg_eta = eta.get(f"tp{i}_sec") or eta.get(f"tp{i}")
        prob = None
        if probs:
            prob = probs.get(f"tp{i}") or probs.get(f"tp{i}_prob") or probs.get(f"prob_tp{i}")
        qtxt = f"x{qty}" if (isinstance(qty,(int,float)) and float(qty) <= 1) else str(qty or "")
        ptxt = _fmt_pct_prob(prob) if prob is not None else "—"
        lines.append(f"🎯 TP{i}: <code>{_fmt_num(px, 4)}</code> · split <code>{qtxt}</code> · ETA { _fmt_eta(leg_eta) } · p={ptxt}")
    return lines

def _trade_kind(plan: Dict[str, Any]) -> str:
    # futures/grid/spot/regular
    kind = (plan.get("trade_kind") or plan.get("mode") or plan.get("market") or "").lower()
    if "grid" in kind:
        return "Grid"
    if "spot" in kind:
        return "Spot"
    return "Futures"

def _fmt_side(side: str) -> str:
    s = (side or "").upper()
    if s in ("BUY","LONG"):
        return "LONG 🟢"
    if s in ("SELL","SHORT"):
        return "SHORT 🔴"
    return s or "—"

def _fmt_order_type(order_type: str) -> str:
    t = (order_type or "").upper()
    if t == "LIMIT":
        return "LIMIT ⛳"
    if t == "MARKET":
        return "MARKET ⚡"
    return (order_type or "—").upper()

def _trim_reason(reason: Any, limit: int = 240) -> str:
    text = ""
    if isinstance(reason, str):
        text = reason
    elif isinstance(reason, list):
        text = "; ".join([str(x) for x in reason if x])
    elif isinstance(reason, dict):
        text = reason.get("why") or reason.get("explain") or reason.get("summary") or ""
    text = text.strip()
    if len(text) > limit:
        text = text[:limit-1] + "…"
    return text or "—"

def _build_trade_urls(idem: str) -> Dict[str, str]:
    if not PUBLIC_HOST:
        return {"approve": "", "reject": "", "ticket": ""}
    base = PUBLIC_HOST
    qs = urlencode({"id": idem})
    return {
        "approve": f"{base}/trade/approve?{qs}",
        "reject":  f"{base}/trade/reject?{qs}",
        "ticket":  f"{base}/trade/ticket?{qs}",
    }

async def send_trade_approval(idem: str, plan: Dict[str, Any], chat_id: Optional[int] = None) -> None:
    """
    הודעת אישור טרייד עשירה עם כל הפרטים (LIMIT/MARKET, מינוף, מחיר נוכחי, SL/TP1-3 עם ETA, סיכויים, רווח צפוי וכו').
    מצפה לשדות (אם חסר—נדלג/נציג '—'):
      symbol, side, leverage, order_type, entry_price/limit_price/price,
      now_price (אופציונלי—ננסה להשיג אם חסר), sl:{stopPrice}, tp:[{stopPrice,qty}],
      budget_usd/expected_pnl_usd, probs:{overall,tp1,tp2,tp3}, eta:{entry_sec,tp1_sec,tp2_sec,tp3_sec},
      reason/explain, trade_kind.
    """
    symbol  = str(plan.get("symbol","")).upper()
    side    = _fmt_side(str(plan.get("side","")))
    lev     = plan.get("leverage") or plan.get("lev") or "—"
    otype   = _fmt_order_type(str(plan.get("order_type") or plan.get("entry_type") or "MARKET"))
    entry   = plan.get("entry_price") or plan.get("limit_price") or plan.get("price")
    now_px  = plan.get("now_price")
    if now_px in (None, 0, "0"):
        now_px = _try_get_live_price(symbol)
    sl_obj  = plan.get("sl") or {}
    sl_px   = sl_obj.get("stopPrice") or sl_obj.get("price")
    tp_legs = plan.get("tp") or plan.get("tp_orders") or []
    budget  = plan.get("budget_usd") or plan.get("budget") or plan.get("budget_used")
    exp_pnl = plan.get("expected_pnl_usd") or plan.get("expected_usd") or None

    probs   = plan.get("prob") or plan.get("probs") or {}
    eta     = plan.get("eta") or {}
    eta_entry = eta.get("entry_sec") or eta.get("entry")  # שניות

    reason  = plan.get("why") or plan.get("explain") or plan.get("reasons")
    why_txt = _trim_reason(reason)

    kind    = _trade_kind(plan)
    created = plan.get("created_at")  # ISO
    il_ts   = _fmt_il(time.time())

    # שורת כותרת
    lines: list[str] = []
    lines.append(f"🟡 <b>Trade Pending Approval</b> · <b>{kind}</b>")
    lines.append(f"🪙 <b>{symbol}</b> · {side} · lev <b>{lev}</b> · {otype}")
    lines.append(f"💫 Now ~ <code>{_fmt_num(now_px, 4)}</code> · 🎯 Entry ~ <code>{_fmt_num(entry, 4)}</code> · ⏳ ETA entry { _fmt_eta(eta_entry) }")
    lines.append(f"🛡 SL: <code>{_fmt_num(sl_px, 4)}</code>")

    # TP1/2/3
    lines += _tp_legs_to_lines(tp_legs, eta=eta, probs=probs)

    # סיכויים/כסף
    overall_p = probs.get("overall") or probs.get("success") or probs.get("p_overall")
    lines.append(f"📈 Success (overall): <b>{_fmt_pct_prob(overall_p)}</b> · "
                 f"P(TP1): {_fmt_pct_prob(probs.get('tp1'))} · "
                 f"P(TP2): {_fmt_pct_prob(probs.get('tp2'))} · "
                 f"P(TP3): {_fmt_pct_prob(probs.get('tp3'))}")
    lines.append(f"💸 Budget: {_fmt_usd(budget)} · Expected PnL: {_fmt_usd(exp_pnl)}")

    # הסבר קצר
    lines.append(f"🧠 Why: {why_txt}")

    # זמנים
    lines.append("— — —")
    lines.append(f"🕒 {il_ts}")

    # כפתורים
    urls = _build_trade_urls(idem)
    kb = {"inline_keyboard":[
        [{"text":"✅ Approve", "url": urls["approve"]},
         {"text":"❌ Reject",  "url": urls["reject"]}],
        [{"text":"🧾 Ticket", "url": urls["ticket"]}] if urls["ticket"] else []
    ]}
    await _tg_send_with_markup("\n".join(lines), kb, chat_id=chat_id)

async def send_trade_opened(info: Dict[str, Any]) -> None:
    plan = info.get("plan") or {}
    s = plan.get("symbol","")
    side = _fmt_side(plan.get("side",""))
    qty = plan.get("qty","")
    price = plan.get("entry_price", plan.get("price",""))
    otype = _fmt_order_type(plan.get("order_type",""))
    lev = plan.get("leverage","—")
    kind = _trade_kind(plan)
    await _tg_send(f"🟢 <b>Opened</b> · <b>{kind}</b>\n"
                   f"{s} {side} · qty <code>{qty}</code> · ~<code>{_fmt_num(price,4)}</code> · {otype} · lev <b>{lev}</b>")

async def send_trade_update(info: Dict[str, Any]) -> None:
    plan = info.get("plan") or {}
    s = plan.get("symbol","")
    side = _fmt_side(plan.get("side",""))
    tp = _tp_legs_to_lines(plan.get("tp"))
    sl = (plan.get("sl") or {}).get("stopPrice")
    parts = [f"📈 <b>Update</b> {s} {side}", *tp, f"🛡 SL: <code>{_fmt_num(sl,4)}</code>"]
    await _tg_send("\n".join(parts))

async def send_trade_closed(info: Dict[str, Any]) -> None:
    """
    דוח סיכום (פוסטמורטם) עם ניתוח קצר + ציוני תתי-מחלקות (1–10).
    מצפה לשדות אופציונליים בתוך info:
      pnl_usd, pnl_pct, hit: ["TP1","TP2",...], duration_sec,
      went_well: [str], to_improve: [str],
      scorecards: {"entry_engine": 8, "risk": 9, "sltp": 7, "router": 8, ...},
      overall_score: 1..10
    """
    plan = info.get("plan") or {}
    s = (plan.get("symbol") or info.get("symbol") or "").upper()
    side = _fmt_side(plan.get("side",""))
    kind = _trade_kind(plan)

    pnl_usd = info.get("pnl_usd", info.get("pnl"))
    pnl_pct = info.get("pnl_pct")
    dur     = info.get("duration_sec")
    hit     = info.get("hit") or []  # e.g. ["TP1","TP2"]
    went    = info.get("went_well") or []
    bad     = info.get("to_improve") or []
    scores  = info.get("scorecards") or {}
    overal  = info.get("overall_score")

    entry = plan.get("entry_price") or plan.get("price")
    exit  = info.get("exit_price") or info.get("avg_exit")

    def _rate_line(k: str, v: Any) -> str:
        try:
            v = int(float(v))
            return f"• {k}: {v}/10"
        except Exception:
            return f"• {k}: —"

    lines = [f"🔴 <b>Closed</b> · <b>{kind}</b> · {s} {side}"]
    lines.append(f"💰 PnL: <b>{_fmt_usd(pnl_usd)}</b> ({_fmt_pct_prob(pnl_pct) if pnl_pct is not None else '—'})")
    lines.append(f"🎯 Hit: {', '.join(hit) if hit else '—'}")
    lines.append(f"⏱ Duration: {_fmt_eta(dur)}")
    lines.append(f"↔️ Prices: entry <code>{_fmt_num(entry,4)}</code> → exit <code>{_fmt_num(exit,4)}</code>")
    if went:
        lines.append("✅ Went well:")
        for x in went[:5]:
            lines.append(f"  • {x}")
    if bad:
        lines.append("⚠️ To improve:")
        for x in bad[:5]:
            lines.append(f"  • {x}")
    if scores:
        lines.append("🧪 Scores:")
        for k,v in scores.items():
            lines.append("  " + _rate_line(k,v))
    if overal is not None:
        try:
            overal = int(float(overal))
            lines.append(f"🏁 Overall: <b>{overal}/10</b>")
        except Exception:
            pass
    await _tg_send("\n".join(lines))
