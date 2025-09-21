# utils/telegram_notifier_core.py
# -*- coding: utf-8 -*-
from __future__ import annotations
"""
ליבה ל־Telegram Notifier:
- קונפיגורציה, קישוט הודעות (BSD), Rate-limit + Dedup
- שליחה עם/בלי מקלדת
- Bundling (איגוד הודעות) + פלש
- עזרי זמן/פורמט
- Auto-Approve policy helper
- חנות שינויים (Redis/קובץ)
- דיכוי התראות WS TTL כברירת מחדל (לדוח EOD)
- Heartbeat שעה־שעה ללא ENV
"""

import os
import time
import asyncio
import logging
import hashlib
import hmac
import json
from typing import Any, Dict, Optional, List, Tuple, Sequence
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, quote

# ---- TZ (Asia/Jerusalem) ----
try:
    from zoneinfo import ZoneInfo
    _TZ_IL = ZoneInfo("Asia/Jerusalem")
except Exception:
    _TZ_IL = timezone(timedelta(hours=3))

logger = logging.getLogger("algogpt.tg")

# ===================== Core Telegram Config =====================
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID     = int(os.getenv("TELEGRAM_CHAT_ID", os.getenv("TELEGRAM_APPROVAL_CHAT_ID", "0")) or 0)
API_BASE    = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "").strip().rstrip("/")

# ===================== Decorative prefix/suffix (BSD) =====================
OPS_DECORATE_BSD = os.getenv("OPS_DECORATE_BSD", "1").lower() in ("1","true","yes","on")
BSD_PREFIX = os.getenv("OPS_BSD_PREFIX_TEXT", 'בס"ד').strip()
BSD_SUFFIX = os.getenv("OPS_BSD_SUFFIX_TEXT", "בעזרת השם נעשה ונצליח 🙏").strip()

def _decorate(text: str) -> str:
    if not OPS_DECORATE_BSD:
        return text
    t = (text or "").strip()
    head = t if t.startswith(BSD_PREFIX) else f"{BSD_PREFIX}\n{t}"
    return head if head.endswith(BSD_SUFFIX) else f"{head}\n{BSD_SUFFIX}"

# ===================== Explain flags =====================
_EXPLAIN_ON          = os.getenv("OPS_EXPLAIN_TRADE_TELEGRAM", "1").lower() in ("1","true","yes","on")
EXPLAIN_COOLDOWN_SEC = int(os.getenv("OPS_EXPLAIN_COOLDOWN_SEC", "45"))
EXPLAIN_MAX_PER_MIN  = int(os.getenv("OPS_EXPLAIN_MAX_PER_MIN", "6"))
EXPLAIN_MIN_SCORE    = float(os.getenv("OPS_EXPLAIN_MIN_SCORE", "0"))

# ===================== Bundling / Rate-limit =====================
BUNDLE_ENABLE     = os.getenv("OPS_ALERT_BUNDLING", "1").lower() in ("1","true","yes","on")
BUNDLE_WINDOW_SEC = int(os.getenv("OPS_ALERT_BUNDLE_WINDOW_SEC", "30"))
BUNDLE_MAX_ITEMS  = int(os.getenv("OPS_ALERT_BUNDLE_MAX_ITEMS", "12"))
BUNDLE_TITLE      = os.getenv("OPS_ALERT_BUNDLE_TITLE", "🔔 Ops Alerts")

SEND_MAX_PER_MIN  = int(os.getenv("TG_SEND_MAX_PER_MIN", "25"))
DEDUP_TTL_SEC     = int(os.getenv("TG_DEDUP_TTL_SEC", "20"))

_last_explain_ts: float = 0.0
_win_start: float = 0.0
_sent_in_win: int = 0

_rl_win_start: float = 0.0
_rl_sent_in_win: int = 0
_dedup_map: Dict[str, float] = {}

_bundle_items: List[str] = []
_bundle_task: Optional[asyncio.Task] = None
_bundle_lock = asyncio.Lock()

# ===================== Auto-Approval (TRADES) =====================
TELEGRAM_AUTO_APPROVE = os.getenv("TELEGRAM_AUTO_APPROVE", "0").lower() in ("1","true","yes","on")
try:
    AUTO_APPROVE_BUDGET_MAX_USD = float(os.getenv("AUTO_APPROVE_BUDGET_MAX_USD", "0") or 0.0)
except Exception:
    AUTO_APPROVE_BUDGET_MAX_USD = 0.0
AUTO_APPROVE_NIGHT = os.getenv("AUTO_APPROVE_NIGHT","0").lower() in ("1","true","yes","on")
NIGHT_HOURS_SPEC   = os.getenv("NIGHT_HOURS","").strip()
AUTO_APPROVE_TIER  = (os.getenv("AUTO_APPROVE_TIER","") or "").strip().lower()

# ===================== SL/TP defaults =====================
def _csv_floats(s: str) -> List[float]:
    out: List[float] = []
    for x in (s or "").split(","):
        x = x.strip()
        if not x:
            continue
        try:
            out.append(float(x))
        except Exception:
            pass
    return out

try:
    DEFAULT_SL_BPS = float(os.getenv("DEFAULT_SL_BPS","0") or 0.0)
except Exception:
    DEFAULT_SL_BPS = 0.0
DEFAULT_TP_BPS    = _csv_floats(os.getenv("DEFAULT_TP_BPS",""))
DEFAULT_TP_SPLITS = _csv_floats(os.getenv("DEFAULT_TP_SPLITS",""))

# ===================== Optional Redis (for digests/change-log) =====================
_redis = None
try:
    _redis_url = os.getenv("REDIS_URL","").strip()
    if _redis_url:
        import redis.asyncio as aioredis  # type: ignore
        _redis = aioredis.from_url(_redis_url, decode_responses=True)
except Exception as _e:
    logger.debug({"event":"redis.disabled","reason":str(_e)})

_changes_file = os.getenv("OPS_CHANGES_FILE", "/tmp/ops_changes.jsonl")

# ===================== WS TTL suppression (default: ON) =====================
SUPPRESS_WS_TTL_ALERTS = os.getenv("SUPPRESS_WS_TTL_ALERTS", "1").lower() in ("1","true","yes","on")
_WS_TTL_PATTERNS = (
    "WS price TTL גבוה",
    "WS price TTL high",
)

def _now() -> float: return time.time()
def _now_dt_utc() -> datetime: return datetime.now(timezone.utc)

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

async def _store_change_event(ev: Dict[str, Any]) -> None:
    ev = dict(ev)
    ev.setdefault("ts", _now())
    try:
        if _redis:
            try:
                await _redis.rpush("ops:changes", json.dumps(ev, ensure_ascii=False))
                return
            except Exception as e:
                logger.debug({"event":"redis.store.failed","err":str(e)})
        with open(_changes_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug({"event":"file.store.failed","err":str(e)})

def _is_ws_ttl_alert(text: str) -> bool:
    t = (text or "").strip()
    return any(pat in t for pat in _WS_TTL_PATTERNS)

def _maybe_route_ws_ttl(text: str) -> bool:
    if not SUPPRESS_WS_TTL_ALERTS:
        return False
    if _is_ws_ttl_alert(text):
        try:
            asyncio.create_task(_store_change_event({"kind": "ws_ttl_stale", "text": text, "ts": _now()}))
        except Exception:
            pass
        return True
    return False

# ===================== Low-level send =====================
async def _http_send(text: str, chat_id: Optional[int] = None) -> None:
    if _maybe_route_ws_ttl(text):
        return
    if not BOT_TOKEN or (chat_id is None and CHAT_ID == 0):
        logger.debug({"event":"tg.skip_send","reason":"missing_token_or_chat"})
        return
    if not _rl_allow():
        logger.debug({"event":"tg.rate_limited","drop":True})
        return
    text = _decorate(text)
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
    if _maybe_route_ws_ttl(text):
        return
    if not BOT_TOKEN or (chat_id is None and CHAT_ID == 0):
        logger.debug({"event":"tg.skip_send","reason":"missing_token_or_chat"})
        return
    if not _rl_allow():
        logger.debug({"event":"tg.rate_limited","drop":True})
        return
    text = _decorate(text)
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

# ===================== Bundling helpers =====================
async def _flush_bundle() -> None:
    global _bundle_items, _bundle_task
    async with _bundle_lock:
        if not _bundle_items:
            return
        text = f"{BUNDLE_TITLE}\n" + "\n".join(_bundle_items)
        _bundle_items = []
        _bundle_task = None
    await _tg_send(text)

async def _bundle_timer() -> None:
    try:
        await asyncio.sleep(max(5, BUNDLE_WINDOW_SEC))
        await _flush_bundle()
    except Exception as e:
        logger.debug({"event":"bundle.timer.failed","err":str(e)})

async def _bundle_add(text: str) -> None:
    if not BUNDLE_ENABLE:
        await _tg_send(text)
        return
    async with _bundle_lock:
        _bundle_items.append(text)
        if len(_bundle_items) >= BUNDLE_MAX_ITEMS:
            await _flush_bundle()
            return
        global _bundle_task
        if not _bundle_task or _bundle_task.done():
            _bundle_task = asyncio.create_task(_bundle_timer())

# ===================== Auto-approve policy =====================
def _in_night_hours_il() -> bool:
    if not NIGHT_HOURS_SPEC:
        return False
    try:
        rng = NIGHT_HOURS_SPEC.replace(" ", "")
        if "-" not in rng:
            return False
        a, b = rng.split("-", 1)
        a = int(a); b = int(b)
        now_il = datetime.now(timezone.utc).astimezone(_TZ_IL)
        h = now_il.hour
        if a <= b:
            return a <= h < b
        return h >= a or h < b
    except Exception:
        return False

def should_auto_approve_trade(plan: Dict[str, Any]) -> bool:
    if not TELEGRAM_AUTO_APPROVE:
        return False
    try:
        budget = float(plan.get("budget_usd") or plan.get("budget") or 0.0)
    except Exception:
        budget = 0.0
    if AUTO_APPROVE_BUDGET_MAX_USD and budget > AUTO_APPROVE_BUDGET_MAX_USD:
        return False
    if AUTO_APPROVE_NIGHT and not _in_night_hours_il():
        return False
    return True

# ===================== Change store (load) =====================
async def _load_changes_since(ts_min: float) -> List[Dict[str,Any]]:
    out: List[Dict[str,Any]] = []
    try:
        if _redis:
            items = await _redis.lrange("ops:changes", 0, -1)
            for line in items:
                try:
                    obj = json.loads(line)
                    if float(obj.get("ts", 0)) >= ts_min:
                        out.append(obj)
                except Exception:
                    pass
            return out
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
        logger.debug({"event":"load_changes.failed","err":str(e)})
    return out

# ===================== URL helpers (approval links) =====================
def _get_sign_secret() -> bytes:
    sec = (os.getenv("OPS_SIGN_SECRET","") or os.getenv("WEBHOOK_HMAC_SECRET","") or "").encode("utf-8")
    return sec

def _sign(ticket_id: str, expires_epoch: int) -> str:
    secret = _get_sign_secret()
    if not secret:
        return ""
    msg = f"{ticket_id}:{expires_epoch}".encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()

def _ensure_ticket_urls(change: Dict[str, Any]) -> Dict[str, str]:
    tid     = change.get("ticket_id", "")
    expires = int(change.get("ops_expires") or (int(time.time()) + int(change.get("ttl_sec", 600))))
    approve_url = change.get("approve_url")
    reject_url  = change.get("reject_url")
    ticket_url  = change.get("ticket_url")
    OPS_REQUIRE_ACTION_PARAM = os.getenv("OPS_REQUIRE_ACTION_PARAM","0").lower() in ("1","true","yes","on")

    if PUBLIC_HOST and tid and not (approve_url and reject_url and ticket_url):
        sig = _sign(tid, int(expires))
        q = {"ticket_id": tid, "expires": int(expires)}
        if sig: q["sig"] = sig
        qs = urlencode(q)
        if OPS_REQUIRE_ACTION_PARAM:
            approve_url = approve_url or f"{PUBLIC_HOST}/ops/approve?{qs}&action=approve"
            reject_url  = reject_url  or f"{PUBLIC_HOST}/ops/reject?{qs}&action=reject"
        else:
            approve_url = approve_url or f"{PUBLIC_HOST}/ops/approve?{qs}"
            reject_url  = reject_url  or f"{PUBLIC_HOST}/ops/reject?{qs}"
        ticket_url  = ticket_url  or f"{PUBLIC_HOST}/ops/ticket/{quote(str(tid))}"
    return {"approve": approve_url or "", "reject": reject_url or "", "ticket": ticket_url or ""}

def _build_trade_urls(idem: str, plan: Dict[str, Any]) -> Dict[str, str]:
    if plan.get("approve_url") or plan.get("reject_url") or plan.get("ticket_url"):
        return {
            "approve": str(plan.get("approve_url","")),
            "reject":  str(plan.get("reject_url","")),
            "ticket":  str(plan.get("ticket_url","")),
        }
    if not PUBLIC_HOST:
        return {"approve": "", "reject": "", "ticket": ""}
    qs = urlencode({"id": idem})
    return {
        "approve": f"{PUBLIC_HOST}/trade/approve?{qs}",
        "reject":  f"{PUBLIC_HOST}/trade/reject?{qs}",
        "ticket":  f"{PUBLIC_HOST}/trade/ticket?{qs}",
    }

# ===================== Numeric / text formatting =====================
def _fmt_usd(v: Any) -> str:
    try: return f"${float(v):.2f}"
    except Exception: return "—"

def _fmt_num(v: Any, prec: int = 4) -> str:
    try: return f"{float(v):.{prec}f}"
    except Exception: return "—" if v is None else str(v)

def _fmt_pct(v: float | int | None) -> str:
    try: return f"{float(v):.0f}%"
    except Exception: return "—"

def _fmt_pct_prob(p: Any) -> str:
    try:
        p = float(p)
        if p <= 1.0: p *= 100.0
        return f"{p:.0f}%"
    except Exception:
        return "—"

def _fmt_eta(sec: Any) -> str:
    try:
        s = int(float(sec))
        if s < 60: return f"~{s}s"
        m, s = divmod(s, 60)
        if m < 60: return f"~{m}m{s:02d}s"
        h, m = divmod(m, 60)
        return f"~{h}h {m}m"
    except Exception:
        return "—"

def _em(emoji: str, text: str) -> str:
    return f"{emoji} {text}"

def _fmt_side(side: str) -> str:
    s = (side or "").upper()
    if s in ("BUY","LONG"):  return "LONG 🟢"
    if s in ("SELL","SHORT"):return "SHORT 🔴"
    return s or "—"

def _fmt_order_type(order_type: str) -> str:
    t = (order_type or "").upper()
    if t == "LIMIT":  return "LIMIT ⛳"
    if t == "MARKET": return "MARKET ⚡"
    return t or "—"

def _tp_legs_to_lines(tp_legs: Optional[Sequence[Dict[str, Any]]],
                      eta: Dict[str, Any] | None = None,
                      probs: Dict[str, Any] | None = None) -> list[str]:
    lines: list[str] = []
    if not tp_legs:
        return [f"🎯 TP: —"]
    for i, leg in enumerate(tp_legs, start=1):
        px   = leg.get("stopPrice") or leg.get("price")
        qty  = leg.get("qty") or leg.get("size") or leg.get("split")
        leg_eta = (eta or {}).get(f"tp{i}") or (eta or {}).get(f"tp{i}_sec")
        prob = (probs or {}).get(f"tp{i}") or (probs or {}).get(f"tp{i}_prob") or (probs or {}).get(f"prob_tp{i}")
        try:
            qtxt = f"x{qty}" if (isinstance(qty,(int,float)) and float(qty) <= 1) else str(qty or "")
        except Exception:
            qtxt = str(qty or "")
        ptxt = _fmt_pct_prob(prob) if prob is not None else "—"
        lines.append(f"🎯 TP{i}: <code>{_fmt_num(px, 4)}</code> · split <code>{qtxt}</code> · ETA {_fmt_eta(leg_eta)} · p={ptxt}")
    return lines

# ===================== Price helpers =====================
def _try_get_live_price(symbol: str) -> Optional[float]:
    try:
        from utils.binance_client import get_price
        p = get_price(symbol.upper())
        return float(p) if p is not None else None
    except Exception:
        return None

# ===================== BTC Anchor (market mood) =====================
def _ema(vals: List[float], period: int) -> Optional[float]:
    if not vals or len(vals) < period:
        return None
    k = 2.0 / (period + 1)
    ema = vals[0]
    for v in vals[1:]:
        ema = v * k + ema * (1 - k)
    return float(ema)

def get_btc_anchor_summary() -> str:
    sym = "BTCUSDT"
    try:
        from utils.get_klines import get_klines_sync
        kl = get_klines_sync(sym, interval=os.getenv("ANCHOR_INTERVAL","1h"), limit=60)
        closes = [float(r[4]) for r in kl if r and len(r) > 4]
        if len(closes) >= 30:
            ema21 = _ema(closes[-30:], 21)
            ema50 = _ema(closes[-60:], 50) if len(closes) >= 60 else _ema(closes, 50)
        else:
            ema21 = _ema(closes, 21); ema50 = _ema(closes, 50)
        last = closes[-1] if closes else _try_get_live_price(sym)
        trend = "⬆️ Bullish" if (ema21 and ema50 and ema21 > ema50) else ("⬇️ Bearish" if (ema21 and ema50 and ema21 < ema50) else "➡️ Side")
        arrow = ">" if (ema21 and ema50 and ema21 > ema50) else "<" if (ema21 and ema50 and ema21 < ema50) else "≈"
        return f"🧭 BTC: {_fmt_num(last,2)} · {trend} (EMA21{arrow}EMA50)"
    except Exception:
        price = _try_get_live_price(sym)
        return f"🧭 BTC: {_fmt_num(price,2)} · mood: —"

# ===================== Simple change-ticket helpers / stubs =====================
async def format_change_approval_he(change: Dict[str, Any]) -> str:
    title = change.get("title") or change.get("summary") or "שינוי"
    why = change.get("why") or change.get("reason") or "—"
    return f"🧾 <b>{title}</b>\nלמה: {why}"

async def send_change_approval_he(change: Dict[str, Any]) -> None:
    urls = _ensure_ticket_urls(change)
    kb = {"inline_keyboard": [
        [{"text": "✅ אישור", "url": urls["approve"]},
         {"text": "❌ דחייה", "url": urls["reject"]}],
        ([{"text": "🎟️ Ticket", "url": urls["ticket"]}] if urls["ticket"] else [])
    ]}
    txt = await format_change_approval_he(change)
    await _tg_send_with_markup(txt, kb)

async def route_change_ticket(change: Dict[str, Any]) -> str:
    return str(change.get("ticket_id") or "")

async def send_ops_digest_now() -> None:
    await _flush_bundle()

async def send_eod_report_now(summary: Dict[str, Any]) -> None:
    pnl = summary.get("pnl","—")
    t = summary.get("time","")
    from datetime import timezone as tz
    day0_il = datetime.now(tz.utc).astimezone(_TZ_IL).replace(hour=0, minute=0, second=0, microsecond=0)
    today0 = day0_il.astimezone(tz.utc).timestamp()
    items = await _load_changes_since(today0)
    ws_items = [it for it in items if it.get("kind") == "ws_ttl_stale"]
    last_ws = (ws_items[-1]["text"] if ws_items else "—")
    await _tg_send(f"📘 EOD {t} · PnL: {pnl}\n🛰️ WS TTL Alerts today: {len(ws_items)}\nאחרון: {last_ws}")

# ===================== Heartbeat (every ~60m, no ENV) =====================
_heartbeat_task: Optional[asyncio.Task] = None

async def _heartbeat_loop() -> None:
    # ברירת מחדל: אחת לשעה. רוצה 30 דק'? שנה את המספר ל-1800.
    interval_sec = 3600
    while True:
        try:
            await asyncio.sleep(interval_sec)
            if BOT_TOKEN and CHAT_ID:
                now_il = datetime.now(timezone.utc).astimezone(_TZ_IL).strftime("%Y-%m-%d %H:%M IL")
                await _tg_send(f"🫀 Heartbeat · סריקה פעילה · אין טריידים חדשים · {now_il}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug({"event":"heartbeat.error","err":str(e)})

async def ensure_ops_schedulers_started() -> bool:
    global _heartbeat_task
    if (_heartbeat_task is None) or _heartbeat_task.done():
        _heartbeat_task = asyncio.create_task(_heartbeat_loop())
    return True

# ===================== Public API (exports) =====================
__all__ = [
    "BOT_TOKEN","CHAT_ID","API_BASE","PUBLIC_HOST",
    "set_explain_enabled","get_explain_enabled","EXPLAIN_MIN_SCORE",
    "_tg_send","_tg_send_with_markup","_bundle_add",
    "_store_change_event","_load_changes_since",
    "_fmt_il","_fmt_usd","_fmt_num","_fmt_pct","_fmt_pct_prob","_fmt_eta","_em",
    "_fmt_side","_fmt_order_type","_tp_legs_to_lines","_try_get_live_price",
    "_ensure_ticket_urls","_build_trade_urls","should_auto_approve_trade",
    "get_btc_anchor_summary",
    "format_change_approval_he","send_change_approval_he","route_change_ticket",
    "send_ops_digest_now","send_eod_report_now","ensure_ops_schedulers_started",
]






