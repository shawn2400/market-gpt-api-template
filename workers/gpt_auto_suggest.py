# workers/gpt_auto_suggest.py
from __future__ import annotations
"""
GPT Auto-Suggest worker (Thin) – שולח התראות לטלגרם בלבד.
- רץ כל X דקות
- אופציונלי: מושך Top-K מה-Core + קונטקסט פר סימבול מהשרת שלך
- מריץ GPT, מסנן לפי Quality/Anchor/RR/EntryDist/Cooldown/De-dup
- שולח אל /alerts/trade-ingest (HMAC + Idempotency) → הבוט מפרסם בטלגרם
"""

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

# Top-K דינאמי מה-Core (אופציונלי)
CORE_TOPK_URL   = os.getenv("CORE_TOPK_URL", "").strip()
CORE_TOPK_TOKEN = os.getenv("CORE_TOPK_TOKEN", "").strip()
TOPK_PER_SWEEP  = int(os.getenv("TOPK_PER_SWEEP", "12"))

# קונטקסט סימבול (אופציונלי)
CONTEXT_URL     = os.getenv("CONTEXT_URL", "").strip()   # דוגמא: https://api.yourhost/context?symbol={symbol}
CONTEXT_TOKEN   = os.getenv("CONTEXT_TOKEN", "").strip()
CONTEXT_TIMEOUT = float(os.getenv("CONTEXT_TIMEOUT", "5"))

# Ingest API (הבוט שלך)
ALERTS_BASE     = os.getenv("ALERTS_BASE", "http://localhost:8000")
API_BEARER      = os.getenv("API_BEARER_TOKEN", "").strip()
HMAC_SECRET     = (os.getenv("HMAC_SECRET", "")).encode()

# Telegram info לתצוגה (הוורקר לא שולח ישירות לטלגרם)
TZ_DISPLAY = TZ

if not OPENAI_API_KEY:
    raise SystemExit("OPENAI_API_KEY missing")
if not API_BEARER:
    raise SystemExit("API_BEARER_TOKEN missing (for /alerts/trade-ingest)")

# === OpenAI ===
from openai import AsyncOpenAI
oai = AsyncOpenAI(api_key=OPENAI_API_KEY)

# === HTTP ===
import httpx
SESSION_TIMEOUT = int(os.getenv("WORKER_HTTP_TIMEOUT", "12"))

# === Quality & Anchor (שלך) ===
from utils.quality import compute_quality
from utils.anchor import evaluate_anchor

ANCHOR_MODE = os.getenv("ANCHOR_MODE", "soft").strip().lower()
if ANCHOR_MODE not in ("off", "soft", "hard"):
    ANCHOR_MODE = "soft"

# === Models ===
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
        def f(name, d=None): return obj.get(name, d)
        def ffloat(x):
            try: return float(x) if x is not None else None
            except: return None
        def fint(x):
            try: return int(x) if x is not None else None
            except: return None

        return cls(
            symbol=str(f("symbol","")).upper(),
            side=str(f("side","")).upper(),
            current_price=ffloat(f("current_price")) or 0.0,
            leverage=fint(f("leverage")) or 10,
            entry=ffloat(f("entry")) or 0.0,
            sl=ffloat(f("sl")) or 0.0,
            tp1=ffloat(f("tp1")) or 0.0,
            tp2=ffloat(f("tp2")),
            tp3=ffloat(f("tp3")),
            success_pct=ffloat(f("success_pct")),
            budget_usd=ffloat(f("budget_usd")),
            notional_usd=ffloat(f("notional_usd")),
            qty=ffloat(f("qty")),
            eta_sl=f("eta_sl"),
            eta_tp1=f("eta_tp1"),
            eta_tp2=f("eta_tp2"),
            eta_tp3=f("eta_tp3"),
            reason=f("reason"),
            skip=bool(f("skip", False)),
        )

def format_msg_preview(t: TradeSug, tz: str) -> str:
    def fmt(x): return f"{x:.6f}" if isinstance(x,(int,float)) and x!=0 else "—"
    return (
        f"{t.symbol} {t.side} | now {fmt(t.current_price)} | entry {fmt(t.entry)} | "
        f"SL {fmt(t.sl)} | TP1 {fmt(t.tp1)} | lev x{t.leverage} | %{t.success_pct or 0:.1f} | {tz}"
    )

# === Context fetch (optional) ===
def _build_context_url(symbol: str) -> Optional[str]:
    if not CONTEXT_URL:
        return None
    if "{symbol}" in CONTEXT_URL:
        return CONTEXT_URL.replace("{symbol}", symbol)
    sep = "&" if ("?" in CONTEXT_URL) else "?"
    return f"{CONTEXT_URL}{sep}symbol={symbol}"

async def fetch_symbol_context(symbol: str) -> Optional[str]:
    url = _build_context_url(symbol)
    if not url:
        return None
    headers = {}
    if CONTEXT_TOKEN:
        headers["Authorization"] = f"Bearer {CONTEXT_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=CONTEXT_TIMEOUT) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json() if "application/json" in r.headers.get("content-type","") else r.text
            # נשמור קצר – JSON קומפקטי ומגבלה על אורך
            if isinstance(data, (dict, list)):
                s = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            else:
                s = str(data)
            return s[:1200]  # לא נשרוף טוקנים מיותרים
    except Exception as e:
        print(f"[WARN] context failed for {symbol}: {e}")
        return None

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

async def suggest_one(symbol: str) -> Optional[TradeSug]:
    ctx = await fetch_symbol_context(symbol)
    try:
        resp = await oai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role":"system", "content": GPT_SYSTEM},
                {"role":"user",   "content": gpt_user_prompt(symbol, TZ, ctx)}
            ],
            temperature=0.2,
            response_format={"type":"json_object"},
        )
        raw = resp.choices[0].message.content
        obj = json.loads(raw)
        sug = TradeSug.from_json(obj)
        if not sug.symbol:
            sug.symbol = symbol
        if sug.skip:
            return None
        return sug
    except Exception as e:
        print(f"[WARN] GPT failed for {symbol}: {e}")
        return None

# === Gating & helpers ===
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

def entry_dist_pct(sug: TradeSug) -> float:
    if sug.current_price <= 0 or sug.entry <= 0:
        return 999.0
    return abs(sug.entry - sug.current_price) / sug.current_price * 100.0

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
    if not ts:
        return False
    return (time.time() - ts) < DEDUP_WINDOW_MIN*60

def mark_hash(sug: TradeSug) -> None:
    h = hash_trade(sug)
    _last_hash_ts[(sug.symbol, h)] = time.time()

def gate_with_quality(sug: TradeSug) -> tuple[bool, str, Dict[str, Any]]:
    anchor = evaluate_anchor(sug.side, ANCHOR_MODE)
    q = compute_quality(
        symbol=sug.symbol, side=sug.side,
        entry=sug.entry, sl=sug.sl, tp=sug.tp1,
        leverage=sug.leverage, budget=float(sug.budget_usd or 100.0),
        anchor=anchor, atr=None,
    )

    rr = rr_val(sug.entry, sug.sl, sug.tp1)
    dist = entry_dist_pct(sug)
    sp = float(sug.success_pct or 0.0)

    if q["quality_score"] < MIN_QUALITY_SCORE:
        return False, "min_quality", {"q": q, "rr": rr, "dist": dist, "sp": sp}
    if rr < MIN_RR:
        return False, "min_rr", {"q": q, "rr": rr, "dist": dist, "sp": sp}
    if dist > MAX_ENTRY_DIST_PCT:
        return False, "entry_dist", {"q": q, "rr": rr, "dist": dist, "sp": sp}
    if sp and sp < MIN_SUCCESS_PCT:
        return False, "min_success_pct", {"q": q, "rr": rr, "dist": dist, "sp": sp}
    if not allow_by_cooldown(sug.symbol):
        return False, "cooldown", {"q": q, "rr": rr, "dist": dist, "sp": sp}
    if is_duplicate(sug):
        return False, "duplicate", {"q": q, "rr": rr, "dist": dist, "sp": sp}

    return True, "ok", {"q": q, "rr": rr, "dist": dist, "sp": sp}

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
    except Exception as e:
        print(f"[WARN] CORE_TOPK_URL failed: {e}")
        return None

async def choose_symbols_for_sweep() -> List[str]:
    syms = await fetch_topk_from_core()
    if syms:
        return syms[:TOPK_PER_SWEEP]
    base = SUGGEST_SYMBOLS.copy()
    random.shuffle(base)
    return base[:TOPK_PER_SWEEP]

# === ingest sender ===
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

# === loop ===
async def loop_forever():
    sem = asyncio.Semaphore(OPENAI_MAX_CONCURRENCY)
    lock = asyncio.Lock()
    while True:
        chosen = await choose_symbols_for_sweep()
        print(f"[*] Sweep | candidates={len(chosen)} | cap={MAX_TRADES_PER_SWEEP or '∞'} | interval={TRADE_SUGGEST_INTERVAL}m")

        sent = 0
        start = time.time()

        async def run_symbol(sym: str):
            nonlocal sent
            if MAX_TRADES_PER_SWEEP and (sent >= MAX_TRADES_PER_SWEEP):
                return
            async with sem:
                sug = await suggest_one(sym)
                if not sug:
                    return
                ok, why, dbg = gate_with_quality(sug)
                if not ok:
                    print(f"[SKIP] {sym} via {why} | q={dbg.get('q',{}).get('quality_score')} rr={dbg.get('rr'):.3f} dist={dbg.get('dist'):.3f}% sp={dbg.get('sp')}")
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
                    prev = format_msg_preview(sug, TZ_DISPLAY)
                    print(f"[OK] Ingest → Telegram | {sym} | id={trade_id} | sent={sent} | {prev}")
                except Exception as e:
                    print(f"[ERR] ingest failed for {sym}: {e}")

        await asyncio.gather(*[run_symbol(s) for s in chosen])

        took = time.time() - start
        sleep_sec = max(5, TRADE_SUGGEST_INTERVAL*60 - int(took))
        print(f"[*] Sweep done in {took:.1f}s → sleeping {sleep_sec}s")
        await asyncio.sleep(sleep_sec)

if __name__ == "__main__":
    asyncio.run(loop_forever())


