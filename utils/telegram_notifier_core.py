# utils/telegram_notifier_core.py
from __future__ import annotations

import os, time, asyncio, logging, hashlib, hmac, json
from typing import Any, Dict, Optional, List, Tuple, Sequence
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
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID     = int(os.getenv("TELEGRAM_CHAT_ID", os.getenv("TELEGRAM_APPROVAL_CHAT_ID", "0")) or 0)
API_BASE    = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "").strip().rstrip("/")

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
AUTO_APPROVE_TIER  = os.getenv("AUTO_APPROVE_TIER","").strip().lower()

# ===================== SL/TP defaults (fallbacks) =====================
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

# ===================== Optional Redis (for digests) =====================
_redis = None
try:
    _redis_url = os.getenv("REDIS_URL","").strip()
    if _redis_url:
        import redis.asyncio as aioredis
        _redis = aioredis.from_url(_redis_url, decode_responses=True)
except Exception as _e:
    logger.debug({"event":"redis.disabled","reason":str(_e)})

_changes_file = os.getenv("OPS_CHANGES_FILE", "/tmp/ops_changes.jsonl")

# ===================== Helpers =====================
def set_explain_enabled(v: bool) -> None:
    global _EXPLAIN_ON
    _EXPLAIN_ON = bool(v)

def get_explain_enabled() -> bool:
    return bool(_EXPLAIN_ON)

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

# ===================== Low-level send (with prayer header/footer) =====================
_PRAYER_HDR = os.getenv("MSG_HEADER_BSD", "בס\"ד").strip()
_PRAYER_FTR = os.getenv("MSG_FOOTER_BH", "בעזרת ה׳ נעשה ונצליח ✨🙏").strip()

def _wrap_blessing(text: str) -> str:
    head = f"<b>{_PRAYER_HDR}</b>\n" if _PRAYER_HDR else ""
    foot = f"\n\n<i>{_PRAYER_FTR}</i>" if _PRAYER_FTR else ""
    return head + text + foot

async def _http_send(text: str, chat_id: Optional[int] = None) -> None:
    if not BOT_TOKEN or (chat_id is None and CHAT_ID == 0):
        logger.debug({"event":"tg.skip_send","reason":"missing_token_or_chat"})
        return
    if not _rl_allow():
        logger.debug({"event":"tg.rate_limited","drop":True})
        return
    wrapped = _wrap_blessing(text)
    if not _dedup_allow(wrapped):
        logger.debug({"event":"tg.dup_suppressed"})
        return
    cid = chat_id if chat_id is not None else CHAT_ID
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(f"{API_BASE}/sendMessage", data={
                "chat_id": cid,
                "text": wrapped,
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
    wrapped = _wrap_blessing(text)
    keytext_wrapped = wrapped + json.dumps(reply_markup, sort_keys=True, ensure_ascii=False)
    if not _dedup_allow(keytext_wrapped):
        logger.debug({"event":"tg.dup_suppressed"})
        return
    cid = chat_id if chat_id is not None else CHAT_ID
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(f"{API_BASE}/sendMessage", json={
                "chat_id": cid,
                "text": wrapped,
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

# ===================== Change store =====================
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
    try:
        with open(_changes_file, "a", encoding="utf-8") as f:
            f.write(data + "\n")
    except Exception as e:
        logger.debug({"event":"file.store.failed","err":str(e)})

async def _load_changes_since(ts_min: float) -> List[Dict[str,Any]]:
    out: List[Dict[str,Any]] = []
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

# ===================== URL helpers (approval links) =====================
OPS_REQUIRE_ACTION_PARAM = os.getenv("OPS_REQUIRE_ACTION_PARAM","0").lower() in ("1","true","yes","on")

def _get_sign_secret() -> bytes:
    # תמיכה ב־OPS_SIGN_SECRET (חדש). אם לא קיים — fallback ל־WEBHOOK_HMAC_SECRET הישן.
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
    expires = int(change.get("ops_expires") or (_now() + int(change.get("ttl_sec", 600))))
    approve_url = change.get("approve_url")
    reject_url  = change.get("reject_url")
    ticket_url  = change.get("ticket_url")
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
    # כיבוד approve_url/reject_url שקיבלת בפליילואד
    for k in ("approve_url","reject_url","ticket_url"):
        if plan.get(k):
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

# ===================== Night windows =====================
def _parse_night_windows(spec: str) -> List[Tuple[int,int]]:
    out: List[Tuple[int,int]] = []
    for chunk in (spec or "").split(","):
        chunk = chunk.strip()
        if not chunk: continue
        if "-" in chunk:
            a,b = chunk.split("-",1)
            try:
                out.append((int(a), int(b)))
            except Exception: pass
        else:
            try:
                h = int(chunk)
                out.append((h,h))
            except Exception: pass
    return out

_NIGHT_WINDOWS = _parse_night_windows(NIGHT_HOURS_SPEC)

def _is_now_night_il(now: Optional[datetime] = None) -> bool:
    if not AUTO_APPROVE_NIGHT or not _NIGHT_WINDOWS:
        return False
    now = now or datetime.now(_TZ_IL)
    h = now.hour
    for a,b in _NIGHT_WINDOWS:
        if a <= b and a <= h <= b:
            return True
        if a > b and (h >= a or h <= b):
            return True
    return False

# ===================== Auto-approval decision for trades =====================
def should_auto_approve_trade(plan: Dict[str, Any]) -> bool:
    if TELEGRAM_AUTO_APPROVE:
        return True
    tier = (str(plan.get("tier") or plan.get("account_tier") or "").strip().lower())
    if AUTO_APPROVE_TIER and tier == AUTO_APPROVE_TIER:
        return True
    if _is_now_night_il():
        return True
    try:
        budget = float(plan.get("budget_usd") or plan.get("budget") or plan.get("budget_used") or 0.0)
    except Exception:
        budget = 0.0
    if AUTO_APPROVE_BUDGET_MAX_USD and budget <= AUTO_APPROVE_BUDGET_MAX_USD:
        return True
    return False

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

# ===================== Public helpers for trade text =====================
def _try_get_live_price(symbol: str) -> Optional[float]:
    try:
        from utils.binance_client import get_price
        p = get_price(symbol.upper())
        return float(p) if p else None
    except Exception:
        return None

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
        qtxt = f"x{qty}" if (isinstance(qty,(int,float)) and float(qty) <= 1) else str(qty or "")
        ptxt = _fmt_pct_prob(prob) if prob is not None else "—"
        lines.append(f"🎯 TP{i}: <code>{_fmt_num(px, 4)}</code> · split <code>{qtxt}</code> · ETA {_fmt_eta(leg_eta)} · p={ptxt}")
    return lines

__all__ = [
    "BOT_TOKEN","CHAT_ID","API_BASE","PUBLIC_HOST",
    "set_explain_enabled","get_explain_enabled","EXPLAIN_MIN_SCORE","EXPLAIN_COOLDOWN_SEC","EXPLAIN_MAX_PER_MIN",
    "_tg_send","_tg_send_with_markup","_bundle_add",
    "_store_change_event","_load_changes_since",
    "_fmt_il","_fmt_usd","_fmt_num","_fmt_pct","_fmt_pct_prob","_fmt_eta","_em",
    "_fmt_side","_fmt_order_type","_tp_legs_to_lines","_try_get_live_price",
    "_ensure_ticket_urls","_build_trade_urls","should_auto_approve_trade",
]

