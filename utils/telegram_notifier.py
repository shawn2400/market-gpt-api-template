# utils/telegram_notifier.py
from __future__ import annotations
import os, time, asyncio, logging, hashlib
from typing import Any, Dict, Optional, List

logger = logging.getLogger("algogpt.tg")

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

def set_explain_enabled(v: bool) -> None:
    global _EXPLAIN_ON
    _EXPLAIN_ON = bool(v)

def get_explain_enabled() -> bool:
    return bool(_EXPLAIN_ON)

def _now() -> float:
    return time.time()

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

def _win_tick():
    global _win_start, _sent_in_win
    now = _now()
    if _win_start == 0.0 or (now - _win_start) >= 60.0:
        _win_start = now
        _sent_in_win = 0

async def _bundle_flush():
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

async def _bundle_schedule_flush():
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

async def _bundle_add(msg: str):
    global _bundle_items
    async with _bundle_lock:
        _bundle_items.append(msg)
    await _bundle_schedule_flush()

# ===================== Public Notifications =====================
async def notify_no_trades(): return None

async def notify_scan_error(reason: str):
    txt = f"⚠️ <b>Scan error</b>\n<code>{reason}</code>"
    if BUNDLE_ENABLE: await _bundle_add(txt.replace("\n", " | "))
    else: await _tg_send(txt)

async def notify_ops_alert(msg: str):
    txt = f"🛠 {msg}"
    if BUNDLE_ENABLE: await _bundle_add(txt)
    else: await _tg_send(txt)

async def notify_explain_trade(plan: Dict[str, Any]):
    if not _EXPLAIN_ON: return
    if float(plan.get("score", 0.0)) < EXPLAIN_MIN_SCORE: return
    global _last_explain_ts, _sent_in_win
    _win_tick()
    now = _now()
    if _last_explain_ts and (now - _last_explain_ts) < EXPLAIN_COOLDOWN_SEC: return
    if _sent_in_win >= max(1, EXPLAIN_MAX_PER_MIN): return

    sym   = str(plan.get("symbol","")).upper()
    side  = str(plan.get("side","")).upper()
    lev   = int(plan.get("leverage", 0) or 0)
    entry = float(plan.get("entry", 0.0) or 0.0)
    sl    = float(plan.get("sl", 0.0) or 0.0)
    tp    = float(plan.get("tp", 0.0) or 0.0)
    adx   = float(plan.get("adx", 0.0) or 0.0)
    atr   = float(plan.get("atr", 0.0) or 0.0)
    score = float(plan.get("score", 0.0) or 0.0)
    ema21 = plan.get("ema_21")
    ema50 = plan.get("ema_50")
    macdh = plan.get("macd_hist")
    rsi   = plan.get("rsi")
    trend_ok = "✓" if (ema21 and ema50 and ((float(ema21) > float(ema50) and side=="LONG") or (float(ema21) < float(ema50) and side=="SHORT"))) else "✗"
    macd_ok  = "✓" if (macdh is not None and ((side=="LONG" and float(macdh)>0) or (side=="SHORT" and float(macdh)<0))) else "✗"

    lines = [f"⚙️ <b>Explain Trade</b>", f"<b>{sym}</b> · <b>{side}</b> · lev=<b>{lev}</b>"]
    if ema21 and ema50: lines.append(f"EMA21{'>' if float(ema21)>float(ema50) else '<'}EMA50 {trend_ok}")
    if macdh: lines.append(f"MACD hist {float(macdh):+.4f} {macd_ok}")
    lines.append(f"ADX {adx:.0f} | ATR {atr:.4f}")
    if rsi: lines.append(f"RSI {float(rsi):.1f}")
    lines.append(f"Quality Score: <b>{score:.2f}/10</b>")
    if entry and (sl or tp): lines.append(f"Entry {entry:.4f} | SL {sl:.4f} | TP {tp:.4f}")
    await _tg_send("\n".join(lines))
    _last_explain_ts = now
    _sent_in_win += 1

async def notify_sl_tp_update(symbol: str, side: str, kind: str, value: Any):
    try:
        val = f"{float(value):.4f}" if isinstance(value, (int, float)) or (isinstance(value, str) and value.replace('.','',1).isdigit()) else str(value)
    except Exception:
        val = str(value)
    await _tg_send(f"🔧 <b>{symbol}</b> {side} · {kind.upper()} → <code>{val}</code>")

async def notify_info(text: str): await _tg_send(f"ℹ️ {text}")
async def notify_error(text: str): await _tg_send(f"🚨 {text}")
async def notify_heartbeat(): await _tg_send("🫀 Heartbeat OK")

async def notify_daily_summary(summary: Dict[str, Any]):
    pnl = summary.get("pnl", 0.0)
    t   = summary.get("time", "")
    n   = len(summary.get("trades") or [])
    await _tg_send(f"📘 Daily Summary {t}\nPnL: <b>{pnl:.2f}</b> USDT · trades={n}")

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

__all__ = [
    "set_explain_enabled", "get_explain_enabled",
    "notify_no_trades", "notify_scan_error", "notify_explain_trade",
    "notify_sl_tp_update", "notify_info", "notify_error",
    "notify_heartbeat", "notify_daily_summary", "notify_ops_alert",
    "register_webhook"
]











