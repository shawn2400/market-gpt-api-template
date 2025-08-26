# workers/gpt_auto_suggest.py
# -*- coding: utf-8 -*-
"""
AlgoGPT — GPT Auto-Suggest Worker (Production-Ready)
---------------------------------------------------
מפיק הצעות טרייד חכמות עם GPT לפי Pool סימבולים (Top-K אופציונלי), עם קונטקסט קל מהשרת,
מסנן לפני GPT כדי לחסוך עלות, מבצע gating אחרי GPT, אימות "לא לרדוף" לפני שליחה,
ואז שולח לטלגרם דרך /alerts/trade-ingest.

תכונות:
- Top-K דינמי (CORE_TOPK_URL) או רשימה סטטית (SUGGEST_SYMBOLS)
- קונטקסט:
  - CONTEXT_BATCH_URL (compact) להאצה (מועדף)
  - CONTEXT_URL לכל סימבול (Fallback)
- Pre-filter לפני GPT: score_light, rr_baseline
- Post-gate אחרי GPT: danger_chop / vol_regime→ריסון מינוף
- אימות כניסה “לא רודפים”: entry_zone_pct / entry_ttl_min / confirm_close (אופציונלי)
- Gating איכות: MIN_QUALITY_SCORE, MIN_RR, MAX_ENTRY_DIST_PCT, MIN_SUCCESS_PCT
- Cooldown פר-סימבול + De-dup לפי hash(entry/sl/tp) + Cap חכם
- Idempotency + HMAC בהגשה ל-/alerts/trade-ingest
- Concurrency נשלט (OPENAI_MAX_CONCURRENCY)
- תקרת notional יומית (אופציונלית, Redis או זיכרון מקומי)
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
TRADE_SUGGEST_INTERVAL = int(os.getenv("TRADE_SUGGEST_INTERVAL", "10"))  # דקות בין סבבים
OPENAI_MAX_CONCURRENCY = int(os.getenv("OPENAI_MAX_CONCURRENCY", "2"))
TZ = os.getenv("TZ", "Asia/Jerusalem")

# Gating איכות אחרי GPT
MIN_QUALITY_SCORE   = float(os.getenv("MIN_QUALITY_SCORE", "7.5"))
MIN_SUCCESS_PCT     = float(os.getenv("MIN_SUCCESS_PCT", "70"))
MIN_RR              = float(os.getenv("MIN_RR", "2.0"))
MAX_ENTRY_DIST_PCT  = float(os.getenv("MAX_ENTRY_DIST_PCT", "0.5"))
COOLDOWN_MINUTES    = int(os.getenv("COOLDOWN_MINUTES", "45"))
DEDUP_WINDOW_MIN    = int(os.getenv("DEDUP_WINDOW_MIN", "180"))
MAX_TRADES_PER_SWEEP = int(os.getenv("MAX_TRADES_PER_SWEEP", "0"))  # 0 = ללא תקרה

# Pre-filter לפני GPT (מבוסס קונטקסט)
MIN_SCORE_LIGHT   = float(os.getenv("MIN_SCORE_LIGHT", "0.8"))
MIN_BASELINE_RR   = float(os.getenv("MIN_BASELINE_RR", "1.3"))

# Top-K (אופציונלי)
CORE_TOPK_URL   = os.getenv("CORE_TOPK_URL", "").strip()  # ex: https://host/topk?k=12&interval=15m
CORE_TOPK_TOKEN = os.getenv("CORE_TOPK_TOKEN", "").strip()
TOPK_PER_SWEEP  = int(os.getenv("TOPK_PER_SWEEP", "12"))
TOPK_PER_SWEEP_HOT = int(os.getenv("TOPK_PER_SWEEP_HOT", str(TOPK_PER_SWEEP + 4)))  # בשעות "חמות" נגדיל מעט

# Context endpoints
CONTEXT_URL       = os.getenv("CONTEXT_URL", "").strip()         # per-symbol, ex: https://host/context?symbol={symbol}&interval=15m&limit=120
CONTEXT_TOKEN     = os.getenv("CONTEXT_TOKEN", "").strip()
CONTEXT_TIMEOUT   = float(os.getenv("CONTEXT_TIMEOUT", "5"))
CONTEXT_BATCH_URL = os.getenv("CONTEXT_BATCH_URL", "").strip()   # ex: https://host/context/batch?compact=1&interval=15m&limit=120&symbols={csv}

# Ingest (הבוט שלך דרך routes/trade_sink.py)
ALERTS_BASE     = os.getenv("ALERTS_BASE", "http://localhost:8000").rstrip("/")
API_BEARER      = os.getenv("API_BEARER_TOKEN", "").strip()
HMAC_SECRET     = (os.getenv("HMAC_SECRET", "")).encode()
SESSION_TIMEOUT = int(os.getenv("WORKER_HTTP_TIMEOUT", "12"))

# Anchor / איכות
ANCHOR_MODE = os.getenv("ANCHOR_MODE", "soft").strip().lower()
if ANCHOR_MODE not in ("off", "soft", "hard"):
    ANCHOR_MODE = "soft"

# ריסון מינוף בתנודתיות גבוהה (Post-gate)
MAX_LEV_HIGH_VOL = int(os.getenv("MAX_LEV_HIGH_VOL", "10"))
CLAMP_LEVERAGE_IN_HIGHVOL = os.getenv("CLAMP_LEVERAGE_IN_HIGHVOL", "1").lower() in ("1","true","yes")

# “לא רודפים” (אימות לפני שליחה)
ENTRY_ZONE_PCT     = float(os.getenv("ENTRY_ZONE_PCT","0.15"))  # אחוז סביב entry
ENTRY_TTL_MIN      = int(os.getenv("ENTRY_TTL_MIN","20"))
PRICE_RECHECK_SEC  = int(os.getenv("PRICE_RECHECK_SEC","3"))
REQUIRE_CLOSE_CONFIRM = os.getenv("REQUIRE_CLOSE_CONFIRM","1").lower() in ("1","true","yes")

# תקרה יומית לנוטיונל (אופציונלי)
MAX_DAILY_NOTIONAL = float(os.getenv("MAX_DAILY_NOTIONAL","0"))  # 0=כבוי
USE_REDIS_LIMITS   = os.getenv("USE_REDIS_LIMITS","0").lower() in ("1","true","yes")
if USE_REDIS_LIMITS:
    import redis
    RED = redis.from_url(os.getenv("REDIS_URL","redis://localhost:6379"), decode_responses=True)

# Hot/Calm שעות
HOT_HOURS  = set(int(x) for x in os.getenv("HOT_HOURS","16,17,18,19,20,21,22,23,0,1").split(",") if x.strip().isdigit())
CALM_HOURS = set(int(x) for x in os.getenv("CALM_HOURS","4,5,6,7,8,9").split(",") if x.strip().isdigit())

# ====== External deps in project ======
from utils.quality import compute_quality
from utils.anchor import evaluate_anchor

# ====== OpenAI client ======
oai = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ====== מודל ההצעה ======
@dataclass
class TradeSug:
    symbol: str
    side: str
    current_price: float
    leverage: int
    entry: float
    sl: float
    tp1: float
    tp2: Optional[float]
    tp3: Optional[float]
    success_pct: Optional[float]
    budget_usd: Optional[float]
    notional_usd: Optional[float]
    qty: Optional[float]
    eta_sl: Optional[str]
    eta_tp1: Optional[str]
    eta_tp2: Optional[str]
    eta_tp3: Optional[str]
    reason: Optional[str]
    # חדשים לא "שוברים" אם לא הגיעו:
    entry_zone_pct: Optional[float] = None
    entry_ttl_min: Optional[int] = None
    confirm_close: Optional[bool] = None
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
        return cls(
            symbol=str(g("symbol","")).upper(),
            side=str(g("side","")).upper(),
            current_price=ffloat(g("current_price")) or 0.0,
            leverage=fint(g("leverage")) or 10,
            entry=ffloat(g("entry")) or 0.0,
            sl=ffloat(g("sl")) or 0.0,
            tp1=ffloat(g("tp1")) or 0.0,
            tp2=ffloat(g("tp2")),
            tp3=ffloat(g("tp3")),
            success_pct=ffloat(g("success_pct")),
            budget_usd=ffloat(g("budget_usd")),
            notional_usd=ffloat(g("notional_usd")),
            qty=ffloat(g("qty")),
            eta_sl=g("eta_sl"),
            eta_tp1=g("eta_tp1"),
            eta_tp2=g("eta_tp2"),
            eta_tp3=g("eta_tp3"),
            reason=g("reason"),
            entry_zone_pct=ffloat(g("entry_zone_pct")),
            entry_ttl_min=fint(g("entry_ttl_min")),
            confirm_close=g("confirm_close") if "confirm_close" in obj else None,
            skip=bool(g("skip", False)),
        )

def format_msg_preview(t: TradeSug, tz: str) -> str:
    def fmt(x): 
        try: 
            return f"{float(x):.6f}"
        except: 
            return "—"
    return f"{t.symbol} {t.side} | now {fmt(t.current_price)} | entry {fmt(t.entry)} | SL {fmt(t.sl)} | TP1 {fmt(t.tp1)} | lev x{t.leverage} | %{t.success_pct or 0:.1f} | {tz}"

# ====== כלי HMAC/Idempotency ======
def hmac_hex(body: bytes) -> str:
    if not HMAC_SECRET:
        return ""
    import hmac, hashlib
    return hmac.new(HMAC_SECRET, body, hashlib.sha256).hexdigest()

# ====== HTTP helpers ======
async def send_ingest(trade: Dict[str, Any]) -> Dict[str, Any]:
    """שולח הצעה שנבחרה ל-/alerts/trade-ingest (טלגרם) עם HMAC + Idempotency."""
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
    """מביא קונטקסט מלא/דק לסימבול יחיד (Fallback כשאין batch)."""
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
    """מביא קונטקסט compact במכה (מועדף)."""
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

# ====== GPT prompt ======
GPT_SYSTEM = (
    "You are AlgoGPT trade suggester. Return ONLY strict JSON (no prose). "
    "Keys: symbol, side, current_price, leverage, entry, sl, tp1, tp2, tp3, "
    "success_pct, budget_usd, notional_usd, qty, eta_sl, eta_tp1, eta_tp2, eta_tp3, reason, skip, "
    "entry_zone_pct, entry_ttl_min, confirm_close."
)

def gpt_user_prompt(symbol: str, tz: str, context: Optional[str]) -> str:
    base = (
        f"Generate a SINGLE Binance futures 15m trade idea for {symbol} as of now in timezone {tz}.\n"
        f"Return JSON ONLY with the schema above.\n"
        f"- side ∈ {{LONG, SHORT}}\n"
        f"- leverage default 10\n"
        f"- entry/sl/tp1/tp2/tp3 in price units\n"
        f"- success_pct (0-100)\n"
        f"- budget_usd (e.g., 50 or 100), notional_usd=budget*leverage, qty≈notional/entry\n"
        f"- eta_* strings 'YYYY-MM-DD HH:MM' {tz}\n"
        f"- reason: 1-2 lines\n"
        f"- Do NOT chase price. Propose a limit entry only; include entry_zone_pct (±% around entry) and entry_ttl_min.\n"
        f"- If breakout strategy, set confirm_close=true (candle must close beyond trigger before entry).\n"
        f"- Prefer RR≥2.0, SL by ATR×1.5 or structure.\n"
        f"- If conditions are weak, return {{\"symbol\":\"{symbol}\", \"skip\":true}}.\n"
    )
    if context:
        base += f"\nContext JSON (read-only):\n{context}"
    return base

# ====== זיכרון Cooldown/De-dup ======
_last_sent_ts: Dict[str, float] = {}      # symbol -> ts
_last_hash_ts: Dict[tuple, float] = {}    # (symbol, hash) -> ts

def rr_val(entry: float, sl: float, tp1: float) -> float:
    try:
        risk = abs(entry - sl)
        if risk <= 0:
            return 0.0
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
    base = f"{sug.symbol}|{sug.side}|{sug.entry}|{sug.sl}|{sug.tp1}|{sug.tp2}|{sug.tp3}"
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

# ====== Pre/Post gates using context ======
def _pick_filters(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize filters from either full or compact batch object."""
    if not isinstance(ctx, dict):
        return {}
    if "filters" in ctx and isinstance(ctx["filters"], dict):
        return ctx["filters"]
    f = {}
    if "score_light" in ctx:
        f["score_light"] = ctx.get("score_light")
    if "rr_baseline" in ctx:
        f["rr_baseline"] = ctx.get("rr_baseline")
    if "trending_up" in ctx or "trending_down" in ctx:
        f["trending_up"] = ctx.get("trending_up")
        f["trending_down"] = ctx.get("trending_down")
    return f

def prefilter_from_context(ctx: Optional[Dict[str, Any]]) -> tuple[bool, str]:
    """דילוג לפני GPT: score_light/rr_baseline נמוכים וכו'."""
    if not ctx:
        return True, "no_ctx"
    f = _pick_filters(ctx)
    score = f.get("score_light")
    rr_b  = f.get("rr_baseline")
    try:
        if score is not None and float(score) < MIN_SCORE_LIGHT:
            return False, f"score_light<{MIN_SCORE_LIGHT}"
        if rr_b is not None and float(rr_b) < MIN_BASELINE_RR:
            return False, f"rr_baseline<{MIN_BASELINE_RR}"
    except Exception:
        pass
    return True, "ok"

def postgate_with_context(sug: TradeSug, ctx: Optional[Dict[str, Any]]) -> tuple[bool, str]:
    """אחרי GPT: התאמות תפעוליות לפי תנאי שוק — ללא כפילות מול quality."""
    if not ctx:
        return True, "no_ctx"
    f = _pick_filters(ctx)
    if f.get("danger_chop"):
        return False, "danger_chop"
    vol_regime = f.get("vol_regime")
    if vol_regime == "high" and sug.leverage and MAX_LEV_HIGH_VOL > 0:
        if CLAMP_LEVERAGE_IN_HIGHVOL and sug.leverage > MAX_LEV_HIGH_VOL:
            sug.leverage = MAX_LEV_HIGH_VOL
    return True, "ok"

# ====== Daily notional cap (optional) ======
def _yyyymmdd_now() -> str:
    return datetime.now(ZoneInfo(TZ)).strftime("%Y%m%d")

def _cap_key() -> str:
    return f"cap:notional:{_yyyymmdd_now()}"

def _inc_daily_notional(v: float):
    if MAX_DAILY_NOTIONAL <= 0: 
        return
    try:
        if USE_REDIS_LIMITS:
            RED.incrbyfloat(_cap_key(), float(v))
        else:
            _DAILY["val"] = _DAILY.get("val", 0.0) + float(v)
    except Exception:
        pass

def _get_daily_notional() -> float:
    if MAX_DAILY_NOTIONAL <= 0: 
        return 0.0
    try:
        if USE_REDIS_LIMITS:
            x = RED.get(_cap_key())
            return float(x or 0.0)
        else:
            return float(_DAILY.get("val", 0.0))
    except Exception:
        return 0.0

_DAILY: Dict[str, float] = {}

# ====== בחירת סימבולים לכל סבב ======
def _hour_regime() -> str:
    h = datetime.now(ZoneInfo(TZ)).hour
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

async def choose_symbols_for_sweep() -> List[str]:
    regime = _hour_regime()
    k = TOPK_PER_SWEEP_HOT if regime == "hot" else TOPK_PER_SWEEP
    syms = await fetch_topk_from_core(k)
    if syms:
        return syms[:k]
    base = SUGGEST_SYMBOLS.copy()
    random.shuffle(base)
    return base[:k]

# ====== Stale-buster: לא לרדוף אחרי השוק ======
async def stale_buster(sym: str, sug: TradeSug, ctx: dict|None) -> bool:
    # TTL (אם GPT סיפק — נעדיף אותו)
    ttl_min = int(sug.entry_ttl_min or ENTRY_TTL_MIN)
    # אזור
    zone_pct = float(sug.entry_zone_pct or ENTRY_ZONE_PCT)

    # קבלת מחיר עדכני מהקונטקסט
    latest = ctx
    if not latest and CONTEXT_URL:
        latest = await fetch_context_symbol(sym)
    if not latest:
        return False
    price = float(latest.get("price") or 0.0)
    if price <= 0.0:
        return False

    # בתוך אזור הכניסה?
    band = zone_pct / 100.0 * sug.entry if sug.entry else 0.0
    if band <= 0.0:
        return False
    in_zone = (sug.entry - band <= price <= sug.entry + band)
    if not in_zone:
        # המתן מעט ובדוק שוב — לא רודפים, רק לוודא שלא נפלנו על טיק אחד
        await asyncio.sleep(PRICE_RECHECK_SEC)
        latest = await fetch_context_symbol(sym)
        if not latest: 
            return False
        price = float(latest.get("price") or 0.0)
        in_zone = (sug.entry - band <= price <= sug.entry + band)
        if not in_zone:
            return False

    # אישור סגירה (לפריצות) — אם התבקש ומופעל ENV
    confirm_close = bool(sug.confirm_close) if sug.confirm_close is not None else False
    if REQUIRE_CLOSE_CONFIRM and confirm_close:
        f = (latest.get("filters") or {})
        if sug.side == "LONG" and not f.get("is_breakout_up", False):
            return False
        if sug.side == "SHORT" and not f.get("is_breakout_down", False):
            return False

    # TTL: כאן הוורקר מריץ ומאמת “כאן ועכשיו”; אם תרצה ניהול זמנים קפדני לפי created_ts,
    # תוכל לשמור בשדה ולהשוות — בפועל זה מיותר כי אנחנו בודקים רגע לפני שליחה.
    return True

# ====== הלולאה הראשית ======
async def loop_forever():
    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY missing")
    if not API_BEARER:
        raise SystemExit("API_BEARER_TOKEN missing (for /alerts/trade-ingest)")

    sem = asyncio.Semaphore(OPENAI_MAX_CONCURRENCY)
    lock = asyncio.Lock()

    while True:
        chosen = await choose_symbols_for_sweep()
        regime = _hour_regime()
        print(f"[*] Sweep | regime={regime} | candidates={len(chosen)} | cap={MAX_TRADES_PER_SWEEP or '∞'} | every={TRADE_SUGGEST_INTERVAL}m")

        # קח קונטקסט במכה אם אפשר
        ctx_map: Dict[str, Dict[str, Any]] = {}
        if CONTEXT_BATCH_URL:
            ctx_map = await fetch_context_batch(chosen)

        sent = 0
        sweep_start = time.time()

        async def run_symbol(sym: str):
            nonlocal sent

            # תקרה לסבב
            if MAX_TRADES_PER_SWEEP and (sent >= MAX_TRADES_PER_SWEEP):
                return

            # קונטקסט (batch או per-symbol)
            ctx = ctx_map.get(sym)
            if ctx is None and CONTEXT_URL:
                ctx = await fetch_context_symbol(sym)

            # Pre-filter לפני GPT
            ok_pf, why_pf = prefilter_from_context(ctx)
            if not ok_pf:
                print(f"[SKIP] prefilter {sym}: {why_pf}")
                return

            # הגבלת מקביליות GPT
            async with sem:
                # קונטקסט קצר לפרומפט (רק שדות רלוונטיים)
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
                            {"role": "user", "content": gpt_user_prompt(sym, TZ, ctx_str)},
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
                except Exception as e:
                    print(f"[WARN] GPT failed for {sym}: {e}")
                    return

                # Post-gate לפי קונטקסט
                ok_pg, why_pg = postgate_with_context(sug, ctx)
                if not ok_pg:
                    print(f"[SKIP] postgate {sym}: {why_pg}")
                    return

                # חישובי איכות (RR/EntryDist/Success/Anchor/Quality)
                if (sug.notional_usd is None) and (sug.budget_usd is not None) and (sug.leverage is not None):
                    try:
                        sug.notional_usd = float(sug.budget_usd) * int(sug.leverage)
                    except Exception:
                        pass
                if (sug.qty is None) and (sug.notional_usd is not None) and sug.entry:
                    try:
                        sug.qty = float(sug.notional_usd) / float(sug.entry)
                    except Exception:
                        pass

                anchor = evaluate_anchor(sug.side, ANCHOR_MODE)
                q = compute_quality(
                    symbol=sug.symbol, side=sug.side,
                    entry=sug.entry, sl=sug.sl, tp=sug.tp1,
                    leverage=sug.leverage, budget=float(sug.budget_usd or 100.0),
                    anchor=anchor, atr=None,
                )
                rr = rr_val(sug.entry, sug.sl, sug.tp1)
                dist = entry_dist_pct(sug.entry, sug.current_price)
                sp = float(sug.success_pct or 0.0)

                # Gates
                if ANCHOR_MODE == "hard" and not anchor.allow:
                    print(f"[SKIP] {sym} anchor-hard-block")
                    return
                if q["quality_score"] < MIN_QUALITY_SCORE:
                    print(f"[SKIP] {sym} quality<{MIN_QUALITY_SCORE} ({q['quality_score']})")
                    return
                if rr < MIN_RR:
                    print(f"[SKIP] {sym} rr<{MIN_RR} ({rr:.3f})")
                    return
                if dist > MAX_ENTRY_DIST_PCT:
                    print(f"[SKIP] {sym} entry_dist>{MAX_ENTRY_DIST_PCT}% ({dist:.3f}%)")
                    return
                if sp and sp < MIN_SUCCESS_PCT:
                    print(f"[SKIP] {sym} success_pct<{MIN_SUCCESS_PCT} ({sp})")
                    return
                if not allow_by_cooldown(sug.symbol):
                    print(f"[SKIP] {sym} cooldown")
                    return
                if is_duplicate(sug):
                    print(f"[SKIP] {sym} duplicate")
                    return

                # תקרה יומית (אופציונלי)
                if MAX_DAILY_NOTIONAL > 0:
                    today = _get_daily_notional()
                    prospective = float(sug.notional_usd or 0.0)
                    if today + prospective > MAX_DAILY_NOTIONAL:
                        print(f"[SKIP] {sym} daily_notional_cap exceeded ({today + prospective:.2f} > {MAX_DAILY_NOTIONAL:.2f})")
                        return

                # אימות "לא רודפים": מחיר באזור, TTL, אישור סגירה אם צריך
                ok_now = await stale_buster(sym, sug, ctx)
                if not ok_now:
                    print(f"[SKIP] {sym} stale/zone/confirm")
                    return

                # שליחה ל-ingest (טלגרם)
                # (שמנו lock קל רק סביב מונה sent כדי להימנע מחריגה מה-cap)
                async with lock:
                    if MAX_TRADES_PER_SWEEP and (sent >= MAX_TRADES_PER_SWEEP):
                        return
                    sent += 1

                trade_id = uuid.uuid4().hex[:8]
                trade = {
                    "trade_id": trade_id,
                    "symbol": sug.symbol,
                    "side": sug.side,
                    "current_price": sug.current_price,
                    "leverage": sug.leverage,
                    "entry": sug.entry,
                    "sl": sug.sl,
                    "tp1": sug.tp1,
                    "tp2": sug.tp2,
                    "tp3": sug.tp3,
                    "success_pct": sug.success_pct,
                    "budget_usd": sug.budget_usd,
                    "notional_usd": sug.notional_usd or ((sug.budget_usd or 0) * (sug.leverage or 1)),
                    "qty": sug.qty,
                    "eta_sl": sug.eta_sl,
                    "eta_tp1": sug.eta_tp1,
                    "eta_tp2": sug.eta_tp2,
                    "eta_tp3": sug.eta_tp3,
                    "reason": sug.reason,
                }
                try:
                    res = await send_ingest(trade)
                    if MAX_DAILY_NOTIONAL > 0:
                        _inc_daily_notional(float(trade["notional_usd"] or 0.0))
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

# ====== Entrypoint ======
if __name__ == "__main__":
    asyncio.run(loop_forever())






