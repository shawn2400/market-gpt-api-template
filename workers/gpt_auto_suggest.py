# workers/gpt_auto_suggest.py
from __future__ import annotations
import os, json, asyncio, time, uuid, hashlib, random
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv(override=False)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o").strip()

SUGGEST_SYMBOLS = [s.strip().upper() for s in os.getenv("SUGGEST_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]
TRADE_SUGGEST_INTERVAL = int(os.getenv("TRADE_SUGGEST_INTERVAL", "10"))  # minutes
OPENAI_MAX_CONCURRENCY = int(os.getenv("OPENAI_MAX_CONCURRENCY", "2"))
TZ = os.getenv("TZ", "Asia/Jerusalem")

# Gating
MIN_QUALITY_SCORE = float(os.getenv("MIN_QUALITY_SCORE", "7.5"))
MIN_SUCCESS_PCT   = float(os.getenv("MIN_SUCCESS_PCT", "70"))
MIN_RR            = float(os.getenv("MIN_RR", "2.0"))
MAX_ENTRY_DIST_PCT = float(os.getenv("MAX_ENTRY_DIST_PCT", "0.5"))
COOLDOWN_MINUTES   = int(os.getenv("COOLDOWN_MINUTES", "45"))
DEDUP_WINDOW_MIN   = int(os.getenv("DEDUP_WINDOW_MIN", "180"))
MAX_TRADES_PER_SWEEP = int(os.getenv("MAX_TRADES_PER_SWEEP", "0"))  # 0 = בלי תקרה

# Pre-filter מהקונטקסט (ללא GPT)
MIN_SCORE_LIGHT   = float(os.getenv("MIN_SCORE_LIGHT", "0.8"))   # אם score_light נמוך → אל תריץ GPT
MIN_BASELINE_RR   = float(os.getenv("MIN_BASELINE_RR", "1.3"))   # דרישת rr_baseline (לפני GPT)

# Top-K דינמי (אופציונלי)
CORE_TOPK_URL   = os.getenv("CORE_TOPK_URL", "").strip()
CORE_TOPK_TOKEN = os.getenv("CORE_TOPK_TOKEN", "").strip()
TOPK_PER_SWEEP  = int(os.getenv("TOPK_PER_SWEEP", "12"))

# קונטקסט
CONTEXT_URL       = os.getenv("CONTEXT_URL", "").strip()         # per-symbol
CONTEXT_TOKEN     = os.getenv("CONTEXT_TOKEN", "").strip()
CONTEXT_TIMEOUT   = float(os.getenv("CONTEXT_TIMEOUT", "5"))
CONTEXT_BATCH_URL = os.getenv("CONTEXT_BATCH_URL", "").strip()   # batch (compact)
# דוגמה: https://your-host/context/batch?compact=1&interval=15m&limit=120&symbols={csv}

# Ingest (הבוט שלך)
ALERTS_BASE     = os.getenv("ALERTS_BASE", "http://localhost:8000")
API_BEARER      = os.getenv("API_BEARER_TOKEN", "").strip()
HMAC_SECRET     = (os.getenv("HMAC_SECRET", "")).encode()

# עידון מינוף לפי תנודתיות
MAX_LEV_HIGH_VOL = int(os.getenv("MAX_LEV_HIGH_VOL", "10"))   # בתנודתיות גבוהה — נרסן מינוף
CLAMP_LEVERAGE_IN_HIGHVOL = os.getenv("CLAMP_LEVERAGE_IN_HIGHVOL","1").lower() in ("1","true","yes")

from openai import AsyncOpenAI
oai = AsyncOpenAI(api_key=OPENAI_API_KEY)

import httpx
SESSION_TIMEOUT = int(os.getenv("WORKER_HTTP_TIMEOUT", "12"))

from utils.quality import compute_quality
from utils.anchor import evaluate_anchor

ANCHOR_MODE = os.getenv("ANCHOR_MODE", "soft").strip().lower()
if ANCHOR_MODE not in ("off", "soft", "hard"):
    ANCHOR_MODE = "soft"

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
            skip=bool(g("skip", False)),
        )

def format_msg_preview(t: TradeSug, tz: str) -> str:
    def fmt(x): return f"{x:.6f}" if isinstance(x,(int,float)) and x!=0 else "—"
    return f"{t.symbol} {t.side} | now {fmt(t.current_price)} | entry {fmt(t.entry)} | SL {fmt(t.sl)} | TP1 {fmt(t.tp1)} | lev x{t.leverage} | %{t.success_pct or 0:.1f} | {tz}"

# === Context fetching ===
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
            # תומך גם ב-compact וגם ב-full
            for it in items:
                sym = (it.get("symbol") or "").upper()
                if not sym: continue
                out[sym] = it
            return out
    except Exception:
        return {}

# === GPT Prompt ===
GPT_SYSTEM = (
    "You are AlgoGPT trade suggester. Return ONLY strict JSON (no prose). "
    "Keys: symbol, side, current_price, leverage, entry, sl, tp1, tp2, tp3, "
    "success_pct, budget_usd, notional_usd, qty, eta_sl, eta_tp1, eta_tp2, eta_tp3, reason, skip. "
    "If no trade, set skip=true and still return the JSON with symbol."
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
        f"If no clear trade, set skip=true."
    )
    if context:
        base += f"\n\nContext JSON (read-only, optional):\n{context}"
    return base

from openai import AsyncOpenAI
oai = AsyncOpenAI(api_key=OPENAI_API_KEY)

# memory for cooldown/dedup
_last_sent_ts: Dict[str, float] = {}
_last_hash_ts: Dict[tuple, float] = {}

def rr_val(entry: float, sl: float, tp1: float) -> float:
    try:
        risk = abs(entry - sl)
        if risk <= 0: return 0.0
        reward = abs(tp1 - entry)
        return reward / risk
    except Exception:
        return 0.0

def entry_dist_pct(entry: float, price: float) -> float:
    if price <= 0 or entry <= 0: return 999.0
    return abs(entry - price) / price * 100.0

def allow_by_cooldown(symbol: str) -> bool:
    last = _last_sent_ts.get(symbol)
    if not last: return True
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
    if not ts: return False
    return (time.time() - ts) < DEDUP_WINDOW_MIN*60

def mark_hash(sug: TradeSug) -> None:
    h = hash_trade(sug)
    _last_hash_ts[(sug.symbol, h)] = time.time()

def hmac_hex(body: bytes) -> str:
    if not HMAC_SECRET:
        return ""
    import hmac, hashlib
    return hmac.new(HMAC_SECRET, body, hashlib.sha256).hexdigest()

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

# --- Pre/Post gates using context ---
def prefilter_from_context(ctx: Optional[Dict[str, Any]]) -> tuple[bool, str]:
    """דילוג לפני GPT: score_light/rr_baseline נמוכים וכו'."""
    if not ctx: 
        return True, "no_ctx"
    f = ctx.get("filters") or {}
    score = f.get("score_light")
    rr_b  = f.get("rr_baseline")
    if score is not None and float(score) < MIN_SCORE_LIGHT:
        return False, f"score_light<{MIN_SCORE_LIGHT}"
    if rr_b is not None and float(rr_b) < MIN_BASELINE_RR:
        return False, f"rr_baseline<{MIN_BASELINE_RR}"
    return True, "ok"

def postgate_with_context(sug: TradeSug, ctx: Optional[Dict[str, Any]]) -> tuple[bool, str]:
    """אחרי GPT: סכינים קלים לפי תנאי שוק, בלי כפילות עם ה-quality."""
    if not ctx:
        return True, "no_ctx"
    f = ctx.get("filters") or {}
    if f.get("danger_chop"):
        return False, "danger_chop"
    vol_regime = f.get("vol_regime")
    if vol_regime == "high" and sug.leverage and MAX_LEV_HIGH_VOL>0:
        if CLAMP_LEVERAGE_IN_HIGHVOL and sug.leverage > MAX_LEV_HIGH_VOL:
            sug.leverage = MAX_LEV_HIGH_VOL  # ריסון מינוף במקום לפסול
        # לא נפסול אם ריסנו מינוף
    return True, "ok"

# === choose symbols ===
async def fetch_topk_from_core() -> Optional[List[str]]:
    if not CORE_TOPK_URL:
        return None
    try:
        headers = {"Authorization": f"Bearer {CORE_TOPK_TOKEN}"} if CORE_TOPK_TOKEN else {}
        async with httpx.AsyncClient(timeout=SESSION_TIMEOUT) as client:
            r = await client.get(CORE_TOPK_URL, headers=headers)
            r.raise_for_status()
            data = r.json()
            syms = data.get("symbols") or []
            return [s.strip().upper() for s in syms][:TOPK_PER_SWEEP]
    except Exception:
        return None

async def choose_symbols_for_sweep() -> List[str]:
    syms = await fetch_topk_from_core()
    if syms:
        return syms[:TOPK_PER_SWEEP]
    base = SUGGEST_SYMBOLS.copy()
    random.shuffle(base)
    return base[:TOPK_PER_SWEEP]

# === loop ===
async def loop_forever():
    sem = asyncio.Semaphore(OPENAI_MAX_CONCURRENCY)
    lock = asyncio.Lock()

    while True:
        chosen = await choose_symbols_for_sweep()
        print(f"[*] Sweep | candidates={len(chosen)} | cap={MAX_TRADES_PER_SWEEP or '∞'} | interval={TRADE_SUGGEST_INTERVAL}m")

        # משוך קונטקסט במכה אם אפשר
        ctx_map: Dict[str, Dict[str, Any]] = {}
        if CONTEXT_BATCH_URL:
            ctx_map = await fetch_context_batch(chosen)

        sent = 0
        start = time.time()

        async def run_symbol(sym: str):
            nonlocal sent
            if MAX_TRADES_PER_SWEEP and (sent >= MAX_TRADES_PER_SWEEP):
                return

            # קונטקסט: batch אם יש, אחרת per symbol
            ctx = ctx_map.get(sym)
            if ctx is None and CONTEXT_URL:
                ctx = await fetch_context_symbol(sym)

            # Pre-filter לפני GPT (חוסך עלות)
            ok_pf, why_pf = prefilter_from_context(ctx)
            if not ok_pf:
                print(f"[SKIP] prefilter {sym}: {why_pf}")
                return

            async with sem:
                # בנה context string קצר ל-prompt אם יש
                ctx_str = None
                if ctx:
                    # compact מועדף: רק price + filters
                    c = {
                        "symbol": ctx.get("symbol"),
                        "price": ctx.get("price"),
                        "filters": {k: ctx.get("filters", {}).get(k) for k in (
                            "trending_up","trending_down","overbought","oversold",
                            "volume_spike","ema_cross_bull","ema_cross_bear","is_breakout_up",
                            "is_breakout_down","atr_pct","rr_baseline","vol_regime","danger_chop","score_light"
                        )}
                    }
                    ctx_str = json.dumps(c, separators=(",", ":"), ensure_ascii=False)

                # GPT
                try:
                    resp = await oai.chat.completions.create(
                        model=OPENAI_MODEL,
                        messages=[{"role":"system","content":GPT_SYSTEM},{"role":"user","content":gpt_user_prompt(sym, TZ, ctx_str)}],
                        temperature=0.2,
                        response_format={"type":"json_object"},
                    )
                    raw = resp.choices[0].message.content
                    obj = json.loads(raw)
                    sug = TradeSug.from_json(obj)
                    if not sug.symbol: sug.symbol = sym
                    if sug.skip: return
                except Exception as e:
                    print(f"[WARN] GPT failed for {sym}: {e}")
                    return

                # Post-gate עם context (רסון מינוף/מצבי שוק)
                ok_pg, why_pg = postgate_with_context(sug, ctx)
                if not ok_pg:
                    print(f"[SKIP] postgate {sym}: {why_pg}")
                    return

                # Quality gates (ללא כפילות מול context)
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
                    mark_sent(sug.symbol)
                    mark_hash(sug)
                    prev = format_msg_preview(sug, TZ)
                    print(f"[OK] Ingest → Telegram | {sym} | id={trade_id} | sent={sent} | {prev}")
                except Exception as e:
                    print(f"[ERR] ingest failed for {sym}: {e}")

        await asyncio.gather(*[run_symbol(s) for s in chosen])

        took = time.time() - start
        sleep_sec = max(5, TRADE_SUGGEST_INTERVAL*60 - int(took))
        print(f"[*] Sweep done in {took:.1f}s → sleeping {sleep_sec}s")
        await asyncio.sleep(sleep_sec)

if __name__ == "__main__":
    if not OPENAI_API_KEY: raise SystemExit("OPENAI_API_KEY missing")
    if not API_BEARER: raise SystemExit("API_BEARER_TOKEN missing (for /alerts/trade-ingest)")
    asyncio.run(loop_forever())



