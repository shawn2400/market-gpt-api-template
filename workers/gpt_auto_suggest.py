# workers/gpt_auto_suggest.py
# -*- coding: utf-8 -*-
"""
AlgoGPT — GPT Auto-Suggest Worker (FUTURES / SPOT / GRID)
---------------------------------------------------------
- תומך בשלושה סוגי טריידים: FUTURES (LONG/SHORT), SPOT, GRID.
- קונטקסט batch/individual, prefilter לפני GPT, postgate אחרי GPT.
- אימות "לא רודפים" (entry_zone / ttl / confirm_close).
- גייטינג מותאם לפי סוג טרייד, כיפות notional יומית (אופציונלי), HMAC/Idempotency ל-ingest.
- “שעות חמות/רגועות” לשינוי MIX/Top-K.

ENV מרכזיים חדשים:
  SUGGEST_MODES=FUTURES,SPOT,GRID
  # GRID thresholds:
  MIN_GRID_LEVELS=4
  MAX_GRID_LEVELS=12
  MIN_GRID_STEP_PCT=0.30
  MAX_GRID_WIDTH_PCT=3.0
  MIN_GRID_BASELINE_RR=1.10
  DEFAULT_GRID_LEVELS=7
  DEFAULT_GRID_STEP_PCT=0.5
"""

from __future__ import annotations
import os, json, asyncio, time, uuid, hashlib, random
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv(override=False)

import httpx
from openai import AsyncOpenAI

# ====== ENV ======
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o").strip()

SUGGEST_SYMBOLS = [s.strip().upper() for s in os.getenv("SUGGEST_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]
SUGGEST_MODES   = [m.strip().upper() for m in os.getenv("SUGGEST_MODES", "FUTURES,SPOT,GRID").split(",") if m.strip()]
TRADE_SUGGEST_INTERVAL = int(os.getenv("TRADE_SUGGEST_INTERVAL", "10"))  # דקות בין סבבים
OPENAI_MAX_CONCURRENCY = int(os.getenv("OPENAI_MAX_CONCURRENCY", "2"))
TZ = os.getenv("TZ", "Asia/Jerusalem")

# Gates כלליים אחרי GPT
MIN_QUALITY_SCORE   = float(os.getenv("MIN_QUALITY_SCORE", "7.5"))
MIN_SUCCESS_PCT     = float(os.getenv("MIN_SUCCESS_PCT", "70"))
MIN_RR              = float(os.getenv("MIN_RR", "2.0"))     # FUTURES ברירת מחדל
MAX_ENTRY_DIST_PCT  = float(os.getenv("MAX_ENTRY_DIST_PCT", "0.5"))
COOLDOWN_MINUTES    = int(os.getenv("COOLDOWN_MINUTES", "45"))
DEDUP_WINDOW_MIN    = int(os.getenv("DEDUP_WINDOW_MIN", "180"))
MAX_TRADES_PER_SWEEP = int(os.getenv("MAX_TRADES_PER_SWEEP", "0"))  # 0 = ללא תקרה

# Gates לפני GPT (קונטקסט)
MIN_SCORE_LIGHT   = float(os.getenv("MIN_SCORE_LIGHT", "0.8"))
MIN_BASELINE_RR   = float(os.getenv("MIN_BASELINE_RR", "1.3"))

# SPOT ספים נפרדים (עדינים יותר)
SPOT_MIN_RR       = float(os.getenv("SPOT_MIN_RR", "1.20"))
SPOT_MIN_SUCCESS  = float(os.getenv("SPOT_MIN_SUCCESS_PCT", "65"))
SPOT_MAX_ENTRY_DIST_PCT = float(os.getenv("SPOT_MAX_ENTRY_DIST_PCT", "0.7"))

# GRID thresholds
MIN_GRID_LEVELS       = int(os.getenv("MIN_GRID_LEVELS", "4"))
MAX_GRID_LEVELS       = int(os.getenv("MAX_GRID_LEVELS", "12"))
MIN_GRID_STEP_PCT     = float(os.getenv("MIN_GRID_STEP_PCT", "0.30"))
MAX_GRID_WIDTH_PCT    = float(os.getenv("MAX_GRID_WIDTH_PCT", "3.0"))
MIN_GRID_BASELINE_RR  = float(os.getenv("MIN_GRID_BASELINE_RR", "1.10"))
DEFAULT_GRID_LEVELS   = int(os.getenv("DEFAULT_GRID_LEVELS", "7"))
DEFAULT_GRID_STEP_PCT = float(os.getenv("DEFAULT_GRID_STEP_PCT", "0.5"))

# Top-K (אופציונלי)
CORE_TOPK_URL   = os.getenv("CORE_TOPK_URL", "").strip()
CORE_TOPK_TOKEN = os.getenv("CORE_TOPK_TOKEN", "").strip()
TOPK_PER_SWEEP  = int(os.getenv("TOPK_PER_SWEEP", "12"))
TOPK_PER_SWEEP_HOT = int(os.getenv("TOPK_PER_SWEEP_HOT", str(TOPK_PER_SWEEP + 4)))

# Context endpoints
CONTEXT_URL       = os.getenv("CONTEXT_URL", "").strip()
CONTEXT_TOKEN     = os.getenv("CONTEXT_TOKEN", "").strip()
CONTEXT_TIMEOUT   = float(os.getenv("CONTEXT_TIMEOUT", "5"))
CONTEXT_BATCH_URL = os.getenv("CONTEXT_BATCH_URL", "").strip()

# Ingest (הגשר לטלגרם)
ALERTS_BASE     = os.getenv("ALERTS_BASE", "http://localhost:8000").rstrip("/")
API_BEARER      = os.getenv("API_BEARER_TOKEN", "").strip()
HMAC_SECRET     = (os.getenv("HMAC_SECRET", "")).encode()
SESSION_TIMEOUT = int(os.getenv("WORKER_HTTP_TIMEOUT", "12"))

# Anchor
ANCHOR_MODE = os.getenv("ANCHOR_MODE", "soft").strip().lower()
if ANCHOR_MODE not in ("off", "soft", "hard"):
    ANCHOR_MODE = "soft"

# Volatility clamp
MAX_LEV_HIGH_VOL = int(os.getenv("MAX_LEV_HIGH_VOL", "10"))
CLAMP_LEVERAGE_IN_HIGHVOL = os.getenv("CLAMP_LEVERAGE_IN_HIGHVOL", "1").lower() in ("1","true","yes")

# “לא רודפים”
ENTRY_ZONE_PCT     = float(os.getenv("ENTRY_ZONE_PCT","0.15"))
ENTRY_TTL_MIN      = int(os.getenv("ENTRY_TTL_MIN","20"))
PRICE_RECHECK_SEC  = int(os.getenv("PRICE_RECHECK_SEC","3"))
REQUIRE_CLOSE_CONFIRM = os.getenv("REQUIRE_CLOSE_CONFIRM","1").lower() in ("1","true","yes")

# Notional cap יומי (אופציונלי)
MAX_DAILY_NOTIONAL = float(os.getenv("MAX_DAILY_NOTIONAL","0"))
USE_REDIS_LIMITS   = os.getenv("USE_REDIS_LIMITS","0").lower() in ("1","true","yes")
if USE_REDIS_LIMITS:
    import redis
    RED = redis.from_url(os.getenv("REDIS_URL","redis://localhost:6379"), decode_responses=True)

# Hot/Calm
HOT_HOURS  = set(int(x) for x in os.getenv("HOT_HOURS","16,17,18,19,20,21,22,23,0,1").split(",") if x.strip().isdigit())
CALM_HOURS = set(int(x) for x in os.getenv("CALM_HOURS","4,5,6,7,8,9").split(",") if x.strip().isdigit())

# ====== project deps ======
from utils.quality import compute_quality
from utils.anchor import evaluate_anchor

# ====== OpenAI client ======
oai = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ====== Models ======
@dataclass
class TradeSug:
    # Common
    trade_type: str            # FUTURES | SPOT | GRID
    symbol: str
    side: Optional[str]        # LONG/SHORT (ל-FUTURES; SPOT יכול להיות רק LONG)
    current_price: float
    entry: float
    sl: Optional[float]
    tp1: Optional[float]
    tp2: Optional[float]
    tp3: Optional[float]
    success_pct: Optional[float]
    reason: Optional[str]

    # FUTURES
    leverage: Optional[int]
    budget_usd: Optional[float]
    notional_usd: Optional[float]
    qty: Optional[float]
    # “לא רודפים”
    entry_zone_pct: Optional[float]
    entry_ttl_min: Optional[int]
    confirm_close: Optional[bool]

    # GRID
    grid_min: Optional[float]
    grid_max: Optional[float]
    grid_levels: Optional[int]
    grid_step_pct: Optional[float]
    grid_take_profit_pct: Optional[float]  # TP per fill (אופציונלי)
    grid_side: Optional[str]               # LONG/SHORT/NEUTRAL (בפועל לרוב LONG/SHORT)

    skip: bool = False

    @classmethod
    def from_json(cls, obj: Dict[str, Any]) -> "TradeSug":
        def g(name, d=None): return obj.get(name, d)
        def ffloat(x):
            try: return float(x) if x is not None else None
            except: return None
        def fint(x):
            try: return int(x) if x is not None else None
            except: return None
        def fbool(x):
            return bool(x) if isinstance(x, bool) else (str(x).lower() in ("1","true","yes"))
        ttype = str(g("trade_type","FUTURES")).upper()
        return cls(
            trade_type=ttype,
            symbol=str(g("symbol","")).upper(),
            side=(str(g("side","")).upper() if g("side") else None),
            current_price=ffloat(g("current_price")) or 0.0,
            entry=ffloat(g("entry")) or 0.0,
            sl=ffloat(g("sl")),
            tp1=ffloat(g("tp1")),
            tp2=ffloat(g("tp2")),
            tp3=ffloat(g("tp3")),
            success_pct=ffloat(g("success_pct")),
            reason=g("reason"),
            leverage=fint(g("leverage")),
            budget_usd=ffloat(g("budget_usd")),
            notional_usd=ffloat(g("notional_usd")),
            qty=ffloat(g("qty")),
            entry_zone_pct=ffloat(g("entry_zone_pct")),
            entry_ttl_min=fint(g("entry_ttl_min")),
            confirm_close=g("confirm_close") if "confirm_close" in obj else None,
            grid_min=ffloat(g("grid_min")),
            grid_max=ffloat(g("grid_max")),
            grid_levels=fint(g("grid_levels")),
            grid_step_pct=ffloat(g("grid_step_pct")),
            grid_take_profit_pct=ffloat(g("grid_take_profit_pct")),
            grid_side=(str(g("grid_side","")).upper() if g("grid_side") else None),
            skip=bool(g("skip", False)),
        )

def format_msg_preview(t: TradeSug, tz: str) -> str:
    def fmt(x): 
        try: 
            return f"{float(x):.6f}"
        except: 
            return "—"
    base = f"{t.trade_type} {t.symbol}"
    if t.trade_type == "GRID":
        w = None
        try:
            if t.grid_min and t.grid_max and t.entry:
                w = abs(t.grid_max - t.grid_min) / t.entry * 100.0
        except: pass
        return f"{base} [{t.grid_side or 'LONG'}] | now {fmt(t.current_price)} | range {fmt(t.grid_min)}–{fmt(t.grid_max)} ({w:.2f}%?) | L={t.grid_levels} step≈{t.grid_step_pct or 0:.2f}% | {tz}"
    # FUTURES/SPOT
    lev = f"x{t.leverage}" if (t.trade_type=="FUTURES" and t.leverage) else ""
    return f"{base} {t.side or ''} {lev} | now {fmt(t.current_price)} | entry {fmt(t.entry)} | SL {fmt(t.sl)} | TP1 {fmt(t.tp1)} | %{t.success_pct or 0:.1f} | {tz}"

# ====== HMAC/Idempotency ======
def hmac_hex(body: bytes) -> str:
    if not HMAC_SECRET:
        return ""
    import hmac, hashlib
    return hmac.new(HMAC_SECRET, body, hashlib.sha256).hexdigest()

# ====== HTTP ======
async def send_ingest(trade: Dict[str, Any]) -> Dict[str, Any]:
    body = json.dumps(trade, separators=(",", ":"), ensure_ascii=False).encode()
    headers = {
        "Authorization": f"Bearer {API_BEARER}",
        "Content-Type": "application/json",
        "X-Idempotency-Key": trade.get("trade_id") or uuid.uuid4().hex,
    }
    sig = hmac_hex(body)
    if sig:
        headers["X-Signature"] = sig
    url = f"{ALERTS_BASE}/alerts/trade-ingest"
    async with httpx.AsyncClient(timeout=SESSION_TIMEOUT) as client:
        r = await client.post(url, content=body, headers=headers)
        r.raise_for_status()
        return r.json()

async def fetch_context_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    if not CONTEXT_URL:
        return None
    url = CONTEXT_URL.replace("{symbol}", symbol) if "{symbol}" in CONTEXT_URL else f"{CONTEXT_URL}{'&' if '?' in CONTEXT_URL else '?'}symbol={symbol}"
    headers = {"Authorization": f"Bearer {CONTEXT_TOKEN}"} if CONTEXT_TOKEN else {}
    try:
        async with httpx.AsyncClient(timeout=CONTEXT_TIMEOUT) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None

async def fetch_context_batch(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    if not CONTEXT_BATCH_URL:
        return {}
    csv = ",".join(symbols)
    url = CONTEXT_BATCH_URL.replace("{csv}", csv)
    headers = {"Authorization": f"Bearer {CONTEXT_TOKEN}"} if CONTEXT_TOKEN else {}
    try:
        async with httpx.AsyncClient(timeout=max(CONTEXT_TIMEOUT, 8.0)) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
            out: Dict[str, Dict[str, Any]] = {}
            items = data.get("items") or []
            for it in items:
                sym = (it.get("symbol") or "").upper()
                if not sym: 
                    continue
                out[sym] = it
            return out
    except Exception:
        return {}

# ====== PROMPTS ======
GPT_SYSTEM = (
    "You are AlgoGPT trade suggester. Return ONLY strict JSON (no prose). "
    "trade_type ∈ {FUTURES, SPOT, GRID}. "
    "For FUTURES/SPOT: keys = trade_type, symbol, side, current_price, entry, sl, tp1, tp2, tp3, "
    "success_pct, reason, leverage, budget_usd, notional_usd, qty, entry_zone_pct, entry_ttl_min, confirm_close, skip. "
    "For GRID: keys = trade_type, symbol, current_price, grid_side, grid_min, grid_max, grid_levels, "
    "grid_step_pct, grid_take_profit_pct, success_pct, reason, skip. "
)

def gpt_user_prompt(symbol: str, tz: str, context: Optional[str], modes: List[str]) -> str:
    mlist = ",".join(modes)
    base = (
        f"Generate ONE trade idea for {symbol} (Binance, 15m) now in timezone {tz}.\n"
        f"Allowed trade_type: {mlist}.\n\n"
        f"Rules FUTURES:\n"
        f"- side ∈ {{LONG, SHORT}}, leverage default 10; limit entry only, provide entry/sl/tp1..tp3.\n"
        f"- Provide success_pct (0-100), reason (1-2 lines), entry_zone_pct (±%), entry_ttl_min, confirm_close.\n"
        f"- budget_usd (e.g., 50-100), notional=budget*leverage, qty≈notional/entry.\n"
        f"- Prefer RR≥2.0; SL by ATR×1.5 or structure.\n\n"
        f"Rules SPOT:\n"
        f"- side=LONG only; leverage=1 (omit or set 1); entry/sl/tp1..tp3; RR≥1.2; success>=65.\n"
        f"- Do NOT chase price.\n\n"
        f"Rules GRID:\n"
        f"- grid_side ∈ {{LONG, SHORT}}; propose range [grid_min..grid_max] around current price, "
        f"  grid_levels (e.g., {DEFAULT_GRID_LEVELS}), grid_step_pct (e.g., {DEFAULT_GRID_STEP_PCT}%).\n"
        f"- Ensure reasonable width (≤ {MAX_GRID_WIDTH_PCT}% of entry), and step ≥ {MIN_GRID_STEP_PCT}%.\n"
        f"- Optional: grid_take_profit_pct per fill.\n"
        f"- If unsuitable market (trending), set skip=true.\n\n"
        f"- If conditions are weak for all, return {{\"trade_type\":\"FUTURES\",\"symbol\":\"{symbol}\",\"skip\":true}}.\n"
        f"Return JSON only.\n"
    )
    if context:
        base += f"\nContext JSON (read-only):\n{context}"
    return base

# ====== Cooldown / dedup / misc ======
_last_sent_ts: Dict[str, float] = {}
_last_hash_ts: Dict[tuple, float] = {}

def rr_val(entry: float, sl: Optional[float], tp1: Optional[float]) -> float:
    try:
        if entry is None or sl is None or tp1 is None:
            return 0.0
        risk = abs(entry - sl)
        if risk <= 0: return 0.0
        reward = abs(tp1 - entry)
        return reward / risk
    except Exception:
        return 0.0

def entry_dist_pct(entry: float, price: float) -> float:
    try:
        if price <= 0 or entry <= 0:
            return 999.0
        return abs(entry - price) / price * 100.0
    except Exception:
        return 999.0

def allow_by_cooldown(symbol: str) -> bool:
    last = _last_sent_ts.get(symbol)
    if not last:
        return True
    return (time.time() - last) >= COOLDOWN_MINUTES * 60

def mark_sent(symbol: str) -> None:
    _last_sent_ts[symbol] = time.time()

def hash_trade(sug: TradeSug) -> str:
    if sug.trade_type == "GRID":
        base = f"{sug.symbol}|GRID|{sug.grid_min}|{sug.grid_max}|{sug.grid_levels}|{sug.grid_step_pct}|{sug.grid_side}"
    else:
        base = f"{sug.symbol}|{sug.trade_type}|{sug.side}|{sug.entry}|{sug.sl}|{sug.tp1}|{sug.tp2}|{sug.tp3}"
    return hashlib.sha256(base.encode()).hexdigest()[:16]

def is_duplicate(sug: TradeSug) -> bool:
    h = hash_trade(sug)
    key = (sug.symbol, h)
    ts = _last_hash_ts.get(key)
    if not ts:
        return False
    return (time.time() - ts) < DEDUP_WINDOW_MIN * 60

def mark_hash(sug: TradeSug) -> None:
    h = hash_trade(sug)
    _last_hash_ts[(sug.symbol, h)] = time.time()

# ====== context helpers ======
def _pick_filters(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(ctx, dict): return {}
    if "filters" in ctx and isinstance(ctx["filters"], dict): return ctx["filters"]
    f = {}
    for k in ("score_light","rr_baseline","trending_up","trending_down","vol_regime","danger_chop"):
        if k in ctx: f[k] = ctx.get(k)
    return f

def prefilter_from_context(ctx: Optional[Dict[str, Any]]) -> tuple[bool, str]:
    if not ctx:
        return True, "no_ctx"
    f = _pick_filters(ctx)
    try:
        score = f.get("score_light")
        rr_b  = f.get("rr_baseline")
        if score is not None and float(score) < MIN_SCORE_LIGHT:
            return False, f"score_light<{MIN_SCORE_LIGHT}"
        if rr_b is not None and float(rr_b) < MIN_BASELINE_RR:
            return False, f"rr_baseline<{MIN_BASELINE_RR}"
    except Exception:
        pass
    return True, "ok"

def postgate_with_context(sug: TradeSug, ctx: Optional[Dict[str, Any]]) -> tuple[bool, str]:
    if not ctx: return True, "no_ctx"
    f = _pick_filters(ctx)
    if f.get("danger_chop") and sug.trade_type == "FUTURES":
        # FUTURES בדשדוש עמוק → עדיף לא
        return False, "danger_chop"
    if f.get("vol_regime") == "high" and sug.trade_type == "FUTURES":
        if CLAMP_LEVERAGE_IN_HIGHVOL and sug.leverage and sug.leverage > MAX_LEV_HIGH_VOL:
            sug.leverage = MAX_LEV_HIGH_VOL
    return True, "ok"

# ====== Notional cap ======
def _yyyymmdd_now(tz: str) -> str:
    return datetime.now(ZoneInfo(tz)).strftime("%Y%m%d")

def _cap_key(tz: str) -> str:
    return f"cap:notional:{_yyyymmdd_now(tz)}"

_DAILY: Dict[str, float] = {}

def _inc_daily_notional(v: float, tz: str):
    if MAX_DAILY_NOTIONAL <= 0: return
    try:
        if USE_REDIS_LIMITS:
            RED.incrbyfloat(_cap_key(tz), float(v))
        else:
            _DAILY["val"] = _DAILY.get("val", 0.0) + float(v)
    except Exception:
        pass

def _get_daily_notional(tz: str) -> float:
    if MAX_DAILY_NOTIONAL <= 0: return 0.0
    try:
        if USE_REDIS_LIMITS:
            x = RED.get(_cap_key(tz))
            return float(x or 0.0)
        else:
            return float(_DAILY.get("val", 0.0))
    except Exception:
        return 0.0

# ====== symbol chooser ======
def _hour_regime(tz: str) -> str:
    h = datetime.now(ZoneInfo(tz)).hour
    if h in HOT_HOURS: return "hot"
    if h in CALM_HOURS: return "calm"
    return "mid"

async def fetch_topk_from_core(k: int) -> Optional[List[str]]:
    if not CORE_TOPK_URL:
        return None
    try:
        url = CORE_TOPK_URL
        if "k=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}k={k}"
        headers = {"Authorization": f"Bearer {CORE_TOPK_TOKEN}"} if CORE_TOPK_TOKEN else {}
        async with httpx.AsyncClient(timeout=SESSION_TIMEOUT) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
            syms = data.get("symbols") or []
            return [s.strip().upper() for s in syms][:k]
    except Exception:
        return None

async def choose_symbols_for_sweep(tz: str) -> List[str]:
    regime = _hour_regime(tz)
    k = TOPK_PER_SWEEP_HOT if regime == "hot" else TOPK_PER_SWEEP
    syms = await fetch_topk_from_core(k)
    if syms:
        return syms[:k]
    base = SUGGEST_SYMBOLS.copy()
    random.shuffle(base)
    return base[:k]

# ====== stale-buster ======
async def stale_buster(sym: str, sug: TradeSug, ctx: dict|None) -> bool:
    if sug.trade_type == "GRID":
        # GRID לא “רץ אחרי מחיר”; רק וידוא טווח/סדר
        if not (sug.grid_min and sug.grid_max and sug.grid_levels):
            return False
        if sug.grid_min >= sug.grid_max:
            return False
        width_pct = abs(sug.grid_max - sug.grid_min) / (sug.entry or sug.current_price or 1.0) * 100.0
        if width_pct > MAX_GRID_WIDTH_PCT:
            return False
        if (sug.grid_step_pct or 0) < MIN_GRID_STEP_PCT:
            return False
        return True

    # FUTURES/SPOT — לא רודפים
    ttl_min = int(sug.entry_ttl_min or ENTRY_TTL_MIN)
    zone_pct = float(sug.entry_zone_pct or ENTRY_ZONE_PCT)

    latest = ctx
    if not latest and CONTEXT_URL:
        latest = await fetch_context_symbol(sym)
    if not latest:
        return False
    price = float(latest.get("price") or 0.0)
    if price <= 0.0:
        return False

    band = zone_pct / 100.0 * (sug.entry or 0.0)
    if band <= 0.0:
        return False
    in_zone = (sug.entry - band <= price <= sug.entry + band)
    if not in_zone:
        await asyncio.sleep(PRICE_RECHECK_SEC)
        latest = await fetch_context_symbol(sym)
        if not latest: 
            return False
        price = float(latest.get("price") or 0.0)
        in_zone = (sug.entry - band <= price <= sug.entry + band)
        if not in_zone:
            return False

    confirm_close = bool(sug.confirm_close) if sug.confirm_close is not None else False
    if REQUIRE_CLOSE_CONFIRM and confirm_close:
        f = (latest.get("filters") or {})
        if (sug.side == "LONG" and not f.get("is_breakout_up", False)) or (sug.side == "SHORT" and not f.get("is_breakout_down", False)):
            return False
    return True

# ====== gates by trade type ======
def type_gates_ok(sug: TradeSug, ctx: Optional[Dict[str, Any]], anchor_mode: str) -> tuple[bool, str]:
    # Anchor
    from utils.anchor import evaluate_anchor
    if sug.trade_type == "FUTURES":
        if not sug.side:
            return False, "futures_missing_side"
        anchor = evaluate_anchor(sug.side, anchor_mode)
        if anchor_mode == "hard" and not anchor.allow:
            return False, "anchor_hard_block"
    # RR / Success / Dist
    if sug.trade_type in ("FUTURES","SPOT"):
        rr = rr_val(sug.entry, sug.sl, sug.tp1)
        dist = entry_dist_pct(sug.entry, sug.current_price)
        sp = float(sug.success_pct or 0.0)

        # FUTURES — קשיחים יותר
        if sug.trade_type == "FUTURES":
            if rr < MIN_RR: return False, f"rr<{MIN_RR}"
            if dist > MAX_ENTRY_DIST_PCT: return False, f"entry_dist>{MAX_ENTRY_DIST_PCT}%"
            if sp and sp < MIN_SUCCESS_PCT: return False, f"success<{MIN_SUCCESS_PCT}"

        # SPOT — עדינים
        if sug.trade_type == "SPOT":
            if rr < SPOT_MIN_RR: return False, f"spot_rr<{SPOT_MIN_RR}"
            if dist > SPOT_MAX_ENTRY_DIST_PCT: return False, f"spot_entry_dist>{SPOT_MAX_ENTRY_DIST_PCT}%"
            if sp and sp < SPOT_MIN_SUCCESS: return False, f"spot_success<{SPOT_MIN_SUCCESS}"
    else:
        # GRID — דרישות מינימליות
        f = _pick_filters(ctx or {})
        rr_b = f.get("rr_baseline")
        if rr_b is not None and float(rr_b) < MIN_GRID_BASELINE_RR:
            return False, f"grid_rr_baseline<{MIN_GRID_BASELINE_RR}"
        if not (sug.grid_min and sug.grid_max and sug.grid_levels):
            return False, "grid_missing_fields"
        if not (MIN_GRID_LEVELS <= int(sug.grid_levels) <= MAX_GRID_LEVELS):
            return False, "grid_levels_out_of_range"
        if (sug.grid_step_pct or 0) < MIN_GRID_STEP_PCT:
            return False, "grid_step_too_small"
        width_pct = abs(sug.grid_max - sug.grid_min) / (sug.entry or sug.current_price or 1.0) * 100.0
        if width_pct > MAX_GRID_WIDTH_PCT:
            return False, "grid_width_too_wide"
    return True, "ok"

# ====== main loop ======
async def loop_forever():
    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY missing")
    if not API_BEARER:
        raise SystemExit("API_BEARER_TOKEN missing")

    sem = asyncio.Semaphore(OPENAI_MAX_CONCURRENCY)
    lock = asyncio.Lock()

    while True:
        chosen = await choose_symbols_for_sweep(TZ)
        regime = _hour_regime(TZ)
        print(f"[*] Sweep | regime={regime} | modes={SUGGEST_MODES} | candidates={len(chosen)} | cap={MAX_TRADES_PER_SWEEP or '∞'} | every={TRADE_SUGGEST_INTERVAL}m")

        ctx_map: Dict[str, Dict[str, Any]] = {}
        if CONTEXT_BATCH_URL:
            ctx_map = await fetch_context_batch(chosen)

        sent = 0
        sweep_start = time.time()

        async def run_symbol(sym: str):
            nonlocal sent

            if MAX_TRADES_PER_SWEEP and (sent >= MAX_TRADES_PER_SWEEP):
                return

            ctx = ctx_map.get(sym)
            if ctx is None and CONTEXT_URL:
                ctx = await fetch_context_symbol(sym)

            ok_pf, why_pf = prefilter_from_context(ctx)
            if not ok_pf:
                print(f"[SKIP] prefilter {sym}: {why_pf}")
                return

            async with sem:
                # מינימל קונטקסט לפרומפט
                ctx_str = None
                if ctx:
                    f = _pick_filters(ctx)
                    c = {
                        "symbol": ctx.get("symbol", sym),
                        "price": ctx.get("price"),
                        "filters": {
                            k: f.get(k) for k in (
                                "trending_up","trending_down","overbought","oversold",
                                "volume_spike","ema_cross_bull","ema_cross_bear",
                                "is_breakout_up","is_breakout_down",
                                "atr_pct","rr_baseline","vol_regime","danger_chop","score_light"
                            ) if k in f
                        }
                    }
                    ctx_str = json.dumps(c, separators=(",", ":"), ensure_ascii=False)

                # GPT
                try:
                    resp = await oai.chat.completions.create(
                        model=OPENAI_MODEL,
                        messages=[
                            {"role": "system", "content": GPT_SYSTEM},
                            {"role": "user", "content": gpt_user_prompt(sym, TZ, ctx_str, SUGGEST_MODES)},
                        ],
                        temperature=0.2,
                        response_format={"type": "json_object"},
                    )
                    raw = resp.choices[0].message.content
                    obj = json.loads(raw)
                    sug = TradeSug.from_json(obj)
                    if not sug.symbol:
                        sug.symbol = sym
                    if sug.skip:
                        return
                    # Normalize types
                    sug.trade_type = (sug.trade_type or "FUTURES").upper()
                    if sug.trade_type == "SPOT":
                        sug.side = "LONG"
                        sug.leverage = 1
                except Exception as e:
                    print(f"[WARN] GPT failed for {sym}: {e}")
                    return

                ok_pg, why_pg = postgate_with_context(sug, ctx)
                if not ok_pg:
                    print(f"[SKIP] postgate {sym}: {why_pg}")
                    return

                # חשב notional/qty אם חסר (FUTURES/SPOT)
                if sug.trade_type in ("FUTURES","SPOT"):
                    if (sug.notional_usd is None) and (sug.budget_usd is not None) and (sug.leverage is not None):
                        try: sug.notional_usd = float(sug.budget_usd) * int(sug.leverage)
                        except: pass
                    if (sug.qty is None) and (sug.notional_usd is not None) and sug.entry:
                        try: sug.qty = float(sug.notional_usd) / float(sug.entry)
                        except: pass

                # איכות (FUTURES/SPOT)
                if sug.trade_type in ("FUTURES","SPOT"):
                    anchor = evaluate_anchor(sug.side or "LONG", ANCHOR_MODE)
                    q = compute_quality(
                        symbol=sug.symbol, side=(sug.side or "LONG"),
                        entry=sug.entry, sl=sug.sl, tp=sug.tp1,
                        leverage=int(sug.leverage or 1), budget=float(sug.budget_usd or 100.0),
                        anchor=anchor, atr=None,
                    )
                    if q["quality_score"] < MIN_QUALITY_SCORE:
                        print(f"[SKIP] {sym} quality<{MIN_QUALITY_SCORE} ({q['quality_score']})")
                        return

                # Gates לפי סוג
                ok_type, why_type = type_gates_ok(sug, ctx, ANCHOR_MODE)
                if not ok_type:
                    print(f"[SKIP] {sym} type_gate: {why_type}")
                    return

                if not allow_by_cooldown(sug.symbol):
                    print(f"[SKIP] {sym} cooldown")
                    return
                if is_duplicate(sug):
                    print(f"[SKIP] {sym} duplicate")
                    return

                # תקרה יומית
                if MAX_DAILY_NOTIONAL > 0 and sug.trade_type in ("FUTURES","SPOT"):
                    today = _get_daily_notional(TZ)
                    prospective = float(sug.notional_usd or 0.0)
                    if today + prospective > MAX_DAILY_NOTIONAL:
                        print(f"[SKIP] {sym} daily_notional_cap ({today + prospective:.2f} > {MAX_DAILY_NOTIONAL:.2f})")
                        return

                # אימות “לא רודפים” / GRID sanity
                ok_now = await stale_buster(sym, sug, ctx)
                if not ok_now:
                    print(f"[SKIP] {sym} stale/zone/grid_sanity")
                    return

                # שליחה ל-ingest
                async with lock:
                    if MAX_TRADES_PER_SWEEP and (sent >= MAX_TRADES_PER_SWEEP):
                        return
                    sent += 1

                trade_id = uuid.uuid4().hex[:8]
                trade: Dict[str, Any] = {
                    "trade_id": trade_id,
                    "trade_type": sug.trade_type,
                    "symbol": sug.symbol,
                    "side": sug.side,
                    "current_price": sug.current_price,
                    "entry": sug.entry,
                    "sl": sug.sl,
                    "tp1": sug.tp1,
                    "tp2": sug.tp2,
                    "tp3": sug.tp3,
                    "success_pct": sug.success_pct,
                    "reason": sug.reason,
                }
                if sug.trade_type in ("FUTURES","SPOT"):
                    trade.update({
                        "leverage": sug.leverage or (1 if sug.trade_type=="SPOT" else 10),
                        "budget_usd": sug.budget_usd,
                        "notional_usd": sug.notional_usd or ((sug.budget_usd or 0) * (sug.leverage or (1 if sug.trade_type=="SPOT" else 10))),
                        "qty": sug.qty,
                        "eta_sl": None, "eta_tp1": None, "eta_tp2": None, "eta_tp3": None,
                    })
                else:
                    # GRID payload
                    trade.update({
                        "grid_min": sug.grid_min,
                        "grid_max": sug.grid_max,
                        "grid_levels": sug.grid_levels or DEFAULT_GRID_LEVELS,
                        "grid_step_pct": sug.grid_step_pct or DEFAULT_GRID_STEP_PCT,
                        "grid_take_profit_pct": sug.grid_take_profit_pct,
                        "grid_side": sug.grid_side or "LONG",
                        # אופציונלי: תקציב כולל לגריד (budget_usd); ללא מינוף ב-SPOT grid
                        "leverage": 1,
                        "budget_usd": sug.budget_usd,
                        "notional_usd": sug.budget_usd,  # בגריד SPOT נוטיונל=תקציב (ללא מינוף)
                        "qty": None,
                    })

                try:
                    res = await send_ingest(trade)
                    if MAX_DAILY_NOTIONAL > 0 and trade["trade_type"] in ("FUTURES","SPOT"):
                        _inc_daily_notional(float(trade["notional_usd"] or 0.0), TZ)
                    mark_sent(sug.symbol)
                    mark_hash(sug)
                    prev = format_msg_preview(sug, TZ)
                    print(f"[OK] Ingest → Telegram | {sym} | id={trade_id} | sent={sent} | {prev}")
                except Exception as e:
                    print(f"[ERR] ingest failed for {sym}: {e}")

        await asyncio.gather(*[run_symbol(s) for s in chosen])

        took = time.time() - sweep_start
        sleep_sec = max(5, TRADE_SUGGEST_INTERVAL * 60 - int(took))
        print(f"[*] Sweep done in {took:.1f}s → sleeping {sleep_sec}s")
        await asyncio.sleep(sleep_sec)

if __name__ == "__main__":
    asyncio.run(loop_forever())







