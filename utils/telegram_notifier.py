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
    class _FixedTZ(timezone.__class__):  # fallback UTC+3
        def __new__(cls): return timezone(timedelta(hours=3))
    _TZ_IL = _FixedTZ()

logger = logging.getLogger("algogpt.tg")

# ===================== Core Telegram Config =====================
BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID        = int(os.getenv("TELEGRAM_CHAT_ID", "0") or 0)
API_BASE       = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

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
# ✅ בקשתך: לא רגיש → אישור אוטומטי; רגיש → אישור ידני; דיג'סט כל 3–5 שעות + דוח יומי.
OPS_AUTO_APPROVE_NON_SENSITIVE = os.getenv("OPS_AUTO_APPROVE_NON_SENSITIVE", "1").lower() in ("1","true","yes","on")
OPS_AUTO_CRS_MAX              = int(os.getenv("OPS_AUTO_CRS_MAX", "6"))  # auto רק עד סיכון 6 כברירת מחדל
OPS_APPROVAL_BASE             = os.getenv("OPS_APPROVAL_BASE", os.getenv("PUBLIC_HOST","")).rstrip("/")
WEBHOOK_HMAC_SECRET           = os.getenv("WEBHOOK_HMAC_SECRET","").strip()

OPS_DIGEST_ENABLE             = os.getenv("OPS_DIGEST_ENABLE","1").lower() in ("1","true","yes","on")
OPS_DIGEST_INTERVAL_HOURS     = max(3, min(5, int(os.getenv("OPS_DIGEST_INTERVAL_HOURS","3"))))  # clamp 3..5
OPS_EOD_ENABLE                = os.getenv("OPS_EOD_ENABLE","1").lower() in ("1","true","yes","on")
OPS_EOD_HOUR_IL               = int(os.getenv("OPS_EOD_HOUR_IL","23"))
OPS_EOD_MINUTE_IL             = int(os.getenv("OPS_EOD_MINUTE_IL","55"))

OPS_APPROVAL_EMOJI            = os.getenv("OPS_APPROVAL_EMOJI","1").lower() in ("1","true","yes","on")

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
    h = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()
    return h

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

# ===================== Public Notifications =====================
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
    entry = float(plan.get("entry", 0.0) or 0.0)
    sl    = float(plan.get("sl", 0.0) or 0.0)
    tp    = float(plan.get("tp", 0.0) or 0.0)
    adx   = float(plan.get("adx", plan.get("dyn", {}).get("adx", 0.0)) or 0.0)
    atr   = float(plan.get("atr", plan.get("dyn", {}).get("atr_pct", 0.0)) or 0.0)
    score = float(plan.get("score", 0.0) or 0.0)
    ema21 = plan.get("ema_21")
    ema50 = plan.get("ema_50")
    macdh = plan.get("macd_hist")
    rsi   = plan.get("rsi")

    trend_ok = "✓" if (ema21 and ema50 and ((float(ema21) > float(ema50) and side=="LONG") or (float(ema21) < float(ema50) and side=="SHORT"))) else "✗"
    macd_ok  = "✓" if (macdh is not None and ((side=="LONG" and float(macdh)>0) or (side=="SHORT" and float(macdh)<0))) else "✗"

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
    public_host = os.getenv("PUBLIC_HOST", "").strip()
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

# ===================== Change-Approval (Hebrew) =====================
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
    il_str  = il_dt.strftime("%Y-%m-%d %H:%М:%S IL")
    return il_str, utc_str

def _sign(ticket_id: str, expires_epoch: int) -> str:
    msg = f"{ticket_id}:{expires_epoch}".encode("utf-8")
    return hmac.new(WEBHOOK_HMAC_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()

def _ensure_urls(change: Dict[str, Any]) -> Dict[str, str]:
    tid = change.get("ticket_id", "")
    expires = int(change.get("ops_expires") or (_now() + int(change.get("ttl_sec", 600))))
    approve_url = change.get("approve_url")
    reject_url  = change.get("reject_url")
    ticket_url  = change.get("ticket_url")

    if OPS_APPROVAL_BASE and WEBHOOK_HMAC_SECRET and tid and not (approve_url and reject_url and ticket_url):
        sig = _sign(tid, int(expires))
        q = urlencode({"ticket_id": tid, "expires": int(expires), "sig": sig})
        approve_url = approve_url or f"{OPS_APPROVAL_BASE}/ops/approve?{q}"
        reject_url  = reject_url  or f"{OPS_APPROVAL_BASE}/ops/reject?{q}"
        ticket_url  = ticket_url  or f"{OPS_APPROVAL_BASE}/ops/ticket/{quote(str(tid))}"

    return {"approve": approve_url or "", "reject": reject_url or "", "ticket": ticket_url or ""}

def format_change_approval_he(change: Dict[str, Any]) -> str:
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

    lines: List[str] = []
    lines.append(f"<b>{_em('🕒','זמן')}</b>: {il_ts} | {utc_ts}")
    lines.append(f"<b>{_em('✅','דרוש אישור שינוי')}</b> (Change Approval)")
    lines.append(f"<b>ID</b>: <code>{tid}</code>")
    lines.append(f"<b>Two-man</b>: {'ON' if two_man else 'OFF'} | <b>TTL</b>: {ttl}s")
    lines.append(f"<b>CRS</b>: {crs}/10 | <b>Sensitive</b>: {'True' if sensitive else 'False'}")
    lines.append(f"<b>Version</b>: <code>{version}</code>")
    lines.append(f"{_em('📝','תכנית')} — {plan}")
    lines.append("— — —")
    try:
        dollars_fmt = f"{float(dollars):.2f}"
    except Exception:
        dollars_fmt = str(dollars)
    lines.append(f"{_em('🖥️','השפעת עומס (משוער)')}: CPU {_fmt_pct(cpu_pct)}, Mem {_fmt_pct(mem_pct)}, API/דקה {_fmt_int(api_rate)}")
    lines.append(f"{_em('💰','עלות (תקרה)')}: ${dollars_fmt} | טוקני AI: {_fmt_int(tokens)} | קריאות API: {_fmt_int(api_max)}")
    t_trd = bool(touches.get("trading", False))
    t_alr = bool(touches.get("alerts", False))
    t_env = bool(touches.get("env", False))
    lines.append(f"{_em('⚙️','שינויים')}: " + (", ".join(changes) if changes else "—"))
    lines.append(f"{_em('🔌','נגיעה ברכיבים')}: Trading={'כן' if t_trd else 'לא'}, Alerts={'כן' if t_alr else 'לא'}, ENV={'כן' if t_env else 'לא'}")
    lines.append(f"{_em('🛡️','בטיחות')}: Canary={'ON' if canary else 'OFF'} | Rollback={'ON' if rollback else 'OFF'}")
    lines.append(_em("ℹ️", "לחיצה על \"אשר\" תפעיל Preflight → Canary → Promote → Post-verify עם ביטול/Rollback אוטומטי אם יש סטייה."))
    return "\n".join(lines)

async def send_change_approval_he(change: Dict[str, Any], chat_id: Optional[int] = None) -> Dict[str, Any] | None:
    if not BOT_TOKEN or not API_BASE:
        logger.debug({"event":"tg.skip_send","reason":"missing_token_or_api"})
        return None
    urls = _ensure_urls(change)
    text = format_change_approval_he(change)

    kb_rows: list[list[dict[str,str]]] = []
    row1 = []
    if urls.get("approve"):
        row1.append({"text": "✅ אשר", "url": urls["approve"]})
    if urls.get("reject"):
        row1.append({"text": "❌ דחה", "url": urls["reject"]})
    if row1: kb_rows.append(row1)
    if urls.get("ticket"):
        kb_rows.append([{"text": "🧾 פרטי הטיקט", "url": urls["ticket"]}])

    reply_markup = {"inline_keyboard": kb_rows}
    try:
        await _tg_send_with_markup(text, reply_markup, chat_id=chat_id)
        return {"ok": True}
    except Exception as e:
        logger.warning({"event":"tg.approval_send_failed","error":str(e)})
        return {"ok": False, "error": str(e)}

# ===================== Change Events Store (for Digest/EOD) =====================
async def _store_change_event(ev: Dict[str, Any]) -> None:
    ev = dict(ev)
    ev.setdefault("ts", _now())
    ev.setdefault("date", datetime.fromtimestamp(ev["ts"], tz=timezone.utc).astimezone(_TZ_IL).strftime("%Y-%m-%d"))
    data = json.dumps(ev, ensure_ascii=False)
    if _redis:
        try:
            await _redis.rpush("ops:changes", data)
            return
        except Exception as e:
            logger.debug({"event":"redis.store.failed","err":str(e)})
    # file fallback
    try:
        with open(_changes_file, "a", encoding="utf-8") as f:
            f.write(data + "\n")
    except Exception as e:
        logger.debug({"event":"file.store.failed","err":str(e)})

async def _load_changes_since(ts_min: float) -> List[Dict[str,Any]]:
    out: List[Dict[str,Any]] = []
    # Prefer Redis
    if _redis:
        try:
            items = await _redis.lrange("ops:changes", 0, -1)
            for line in items:
                try:
                    obj = json.loads(line)
                    if float(obj.get("ts", 0)) >= ts_min:
                        out.append(obj)
                except Exception:
                    pass
            return out
        except Exception as e:
            logger.debug({"event":"redis.load.failed","err":str(e)})
    # file fallback
    try:
        if os.path.exists(_changes_file):
            with open(_changes_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line.strip())
                        if float(obj.get("ts", 0)) >= ts_min:
                            out.append(obj)
                    except Exception:
                        pass
    except Exception as e:
        logger.debug({"event":"file.load.failed","err":str(e)})
    return out

# ===================== Auto-Approve Router =====================
async def _auto_approve_change(change: Dict[str, Any]) -> bool:
    """Clicks the signed Approve URL (HTTP GET)."""
    urls = _ensure_urls(change)
    approve_url = urls.get("approve","")
    if not approve_url:
        return False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.get(approve_url)
            ok = (200 <= r.status_code < 300)
            if not ok:
                logger.warning({"event":"auto_approve.http_error","status":r.status_code,"body":r.text[:256]})
            return ok
    except Exception as e:
        logger.warning({"event":"auto_approve.failed","error":str(e)})
        return False

async def route_change_ticket(change: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main policy:
      - if not sensitive and crs <= OPS_AUTO_CRS_MAX and OPS_AUTO_APPROVE_NON_SENSITIVE=1 -> auto-approve (silent)
      - else -> send approval message to Telegram
    Always records event for digest/EOD.
    """
    sensitive = bool(change.get("sensitive", False))
    crs = float(change.get("crs", 0) or 0)
    tid = str(change.get("ticket_id",""))
    plan = change.get("plan","")
    version = change.get("version","")

    if OPS_AUTO_APPROVE_NON_SENSITIVE and (not sensitive) and crs <= OPS_AUTO_CRS_MAX:
        ok = await _auto_approve_change(change)
        await _store_change_event({
            "kind":"change",
            "ticket_id": tid,
            "status": "auto_approved" if ok else "auto_approve_failed",
            "sensitive": sensitive,
            "crs": crs,
            "plan": plan,
            "version": version,
        })
        if not ok:
            # fallback: send manual approval
            await send_change_approval_he(change)
        return {"ok": True, "auto": True}

    # sensitive or high CRS -> manual approval
    await _store_change_event({
        "kind":"change",
        "ticket_id": tid,
        "status": "awaiting_manual",
        "sensitive": sensitive,
        "crs": crs,
        "plan": plan,
        "version": version,
    })
    await send_change_approval_he(change)
    return {"ok": True, "auto": False}

# ===================== Digest & EOD =====================
async def send_ops_digest_now(hours: Optional[int] = None) -> None:
    """Sends a digest for the last N hours (default = OPS_DIGEST_INTERVAL_HOURS)."""
    interval_h = int(hours or OPS_DIGEST_INTERVAL_HOURS)
    ts_min = _now() - interval_h * 3600
    items = await _load_changes_since(ts_min)
    if not items:
        await _tg_send(f"🧭 דיג'סט תפעולי ({interval_h}ש) — אין עדכונים.")
        return

    total = len(items)
    auto_ok = sum(1 for x in items if x.get("status")=="auto_approved")
    auto_fail = sum(1 for x in items if x.get("status")=="auto_approve_failed")
    manual = sum(1 for x in items if x.get("status")=="awaiting_manual")
    # short list of last 6
    last_lines = []
    for x in items[-6:]:
        line = f"{_fmt_il(x.get('ts'))} · v{(x.get('version') or '—')} · CRS {x.get('crs','?')} · {'Sensitive' if x.get('sensitive') else 'Non-sens'} · {x.get('status')}"
        if x.get("plan"): line += f" · {x['plan']}"
        last_lines.append("• " + line)

    msg = [
        f"🧭 דיג'סט תפעולי ({interval_h}ש) — {total} עדכונים",
        f"Auto OK: {auto_ok} | Auto Fail: {auto_fail} | Manual: {manual}",
        "— — —",
        *last_lines
    ]
    await _tg_send("\n".join(msg))

async def send_eod_report_now() -> None:
    """End-of-day (IL) operational report."""
    # from today 00:00 IL
    now_il = datetime.now(_TZ_IL)
    start_il = now_il.replace(hour=0, minute=0, second=0, microsecond=0)
    ts_min = start_il.astimezone(timezone.utc).timestamp()
    items = await _load_changes_since(ts_min)
    total = len(items)
    auto_ok = sum(1 for x in items if x.get("status")=="auto_approved")
    auto_fail = sum(1 for x in items if x.get("status")=="auto_approve_failed")
    manual = sum(1 for x in items if x.get("status")=="awaiting_manual")

    msg = [
        f"📘 דוח יומי — {now_il.strftime('%Y-%m-%d')} (IL)",
        f"סה\"כ שינויים: {total} | Auto OK: {auto_ok} | Auto Fail: {auto_fail} | Manual: {manual}",
    ]
    # top 8 by recency
    for x in items[-8:]:
        short = (x.get("plan") or "—")
        if len(short) > 70: short = short[:67] + "…"
        msg.append(f"• {_fmt_il(x.get('ts'))} · v{(x.get('version') or '—')} · CRS {x.get('crs','?')} · {'Sensitive' if x.get('sensitive') else 'Non-sens'} · {short}")
    await _tg_send("\n".join(msg))

# Background loops
_digest_task: Optional[asyncio.Task] = None
_eod_task: Optional[asyncio.Task] = None
_schedulers_started: bool = False

def _seconds_until_next_digest(now_il: Optional[datetime] = None) -> int:
    now_il = now_il or datetime.now(_TZ_IL)
    base = now_il.replace(minute=0, second=0, microsecond=0)
    # align to next multiple of interval
    delta_h = OPS_DIGEST_INTERVAL_HOURS - ((now_il.hour - base.hour) % OPS_DIGEST_INTERVAL_HOURS)
    if delta_h == 0 and now_il.minute == 0:
        delta_h = OPS_DIGEST_INTERVAL_HOURS
    target = base + timedelta(hours=delta_h)
    return max(5, int((target - now_il).total_seconds()))

def _seconds_until_eod(now_il: Optional[datetime] = None) -> int:
    now_il = now_il or datetime.now(_TZ_IL)
    target = now_il.replace(hour=OPS_EOD_HOUR_IL, minute=OPS_EOD_MINUTE_IL, second=0, microsecond=0)
    if target <= now_il:
        target = target + timedelta(days=1)
    return max(5, int((target - now_il).total_seconds()))

async def _digest_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_seconds_until_next_digest())
            await send_ops_digest_now()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug({"event":"digest.loop.err","err":str(e)})
            await asyncio.sleep(5)

async def _eod_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_seconds_until_eod())
            await send_eod_report_now()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug({"event":"eod.loop.err","err":str(e)})
            await asyncio.sleep(5)

async def ensure_ops_schedulers_started() -> None:
    """Call this once on app startup."""
    global _schedulers_started, _digest_task, _eod_task
    if _schedulers_started:
        return
    loop = asyncio.get_event_loop()
    if OPS_DIGEST_ENABLE:
        _digest_task = loop.create_task(_digest_loop())
    if OPS_EOD_ENABLE:
        _eod_task = loop.create_task(_eod_loop())
    _schedulers_started = True

# ===================== Public API =====================
__all__ = [
    # flags & simple notifiers
    "set_explain_enabled", "get_explain_enabled",
    "notify_no_trades", "notify_scan_error", "notify_explain_trade",
    "notify_sl_tp_update", "notify_info", "notify_error",
    "notify_heartbeat", "notify_daily_summary", "notify_ops_alert",
    "register_webhook",
    # approvals
    "format_change_approval_he", "send_change_approval_he",
    "route_change_ticket",
    # digests
    "send_ops_digest_now", "send_eod_report_now", "ensure_ops_schedulers_started",
]














