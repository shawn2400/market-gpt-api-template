# workers/gpt_auto_suggest.py
from __future__ import annotations
"""
GPT Auto-Suggest worker (Thin) – שולח התראות לטלגרם בלבד.
- לא תלוי main.py
- לא מושך נתונים חיצוניים
- משתמש ב-GPT בלבד + Gating מקומי (Quality/Anchor/RR/EntryDist/Cooldown/De-dup)
"""

import os, json, asyncio, time, uuid, hashlib, random
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

# === ENV ===
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
MAX_ENTRY_DIST_PCT = float(os.getenv("MAX_ENTRY_DIST_PCT", "0.5"))  # % מהמחיר
COOLDOWN_MINUTES   = int(os.getenv("COOLDOWN_MINUTES", "45"))
DEDUP_WINDOW_MIN   = int(os.getenv("DEDUP_WINDOW_MIN", "180"))

# Cap לסבב: 0 = בלי תקרה (אתה אמרת “כמה שיותר” – בגלל הסינון לא צפוי לעבור ~5 ביום)
MAX_TRADES_PER_SWEEP = int(os.getenv("MAX_TRADES_PER_SWEEP", "0"))

# Top-K דינמי מה-Core (אופציונלי, כדי לחסוך עלות GPT מראש)
CORE_TOPK_URL   = os.getenv("CORE_TOPK_URL", "").strip()
CORE_TOPK_TOKEN = os.getenv("CORE_TOPK_TOKEN", "").strip()
TOPK_PER_SWEEP  = int(os.getenv("TOPK_PER_SWEEP", "12"))

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()
USE_INLINE_BUTTONS = (os.getenv("USE_INLINE_BUTTONS", "0").lower() in ("1","true","yes"))  # עד שתחבר webhook – השאר 0

if not OPENAI_API_KEY:
    raise SystemExit("OPENAI_API_KEY missing")
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise SystemExit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing")

# === OpenAI client ===
from openai import AsyncOpenAI
oai = AsyncOpenAI(api_key=OPENAI_API_KEY)

# === Telegram minimal client ===
import httpx
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

async def tg_send(text: str, kb: Optional[Dict[str, Any]] = None):
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    if kb: payload["reply_markup"] = kb
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
        r.raise_for_status()
        return r.json()

def kb_inline(trade_id: str) -> Dict[str, Any]:
    return {
        "inline_keyboard":[[
            {"text":"✅ אשר","callback_data":f"approve:{trade_id}"},
            {"text":"✏️ כוונן","callback_data":f"adjust:{trade_id}"},
            {"text":"🛑 דחה","callback_data":f"reject:{trade_id}"}
        ]]
    }

# === Quality & Anchor (שלך) ===
from utils.quality import compute_quality
from utils.anchor import evaluate_anchor

ANCHOR_MODE = os.getenv("ANCHOR_MODE", "soft").strip().lower()
if ANCHOR_MODE not in ("off", "soft", "hard"):
    ANCHOR_MODE = "soft"

# === מודל הנתונים שה-GPT מחזיר (JSON) ===
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
        def f(name, default=None): return obj.get(name, default)
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

def format_msg(t: TradeSug, trade_id: str) -> str:
    def fmt(x): return f"`{x:.6f}`" if isinstance(x,(int,float)) and x!=0 else "`—`"
    lines = [
        "🧠 *AlgoGPT — טרייד מוכן*",
        f"*{t.symbol}* | *{t.side}* | מחיר עכשיו: {fmt(t.current_price)}",
        f"כניסה: {fmt(t.entry)} | SL: {fmt(t.sl)} | TP1: {fmt(t.tp1)} | TP2: {fmt(t.tp2)} | TP3: {fmt(t.tp3)}",
        " | ".join([p for p in [
            f"מינוף: `x{t.leverage}`",
            f"תקציב: `${t.budget_usd:.2f}`" if t.budget_usd else None,
            f"Notional: `${t.notional_usd:.2f}`" if t.notional_usd else None,
            f"Qty≈ `{t.qty:.6f}`" if t.qty else None,
        ] if p]),
        (f"% הצלחה: `{t.success_pct:.1f}%`" if t.success_pct is not None else ""),
        "⏱️ *ETAs* — "
        + (f"SL: _{t.eta_sl}_ | " if t.eta_sl else "SL: _—_ | ")
        + (f"TP1: _{t.eta_tp1}_ | " if t.eta_tp1 else "TP1: _—_ | ")
        + (f"TP2: _{t.eta_tp2}_ | " if t.eta_tp2 else "TP2: _—_ | ")
        + (f"TP3: _{t.eta_tp3}_" if t.eta_tp3 else "TP3: _—_"),
        (f"סיבה: {t.reason}" if t.reason else "")
    ]
    lines.append(f"\nID: `{trade_id}`  | TZ: `{TZ}`")
    return "\n".join([ln for ln in lines if ln])

GPT_SYSTEM = (
    "You are AlgoGPT trade suggester. Return ONLY strict JSON (no prose). "
    "Keys: symbol, side, current_price, leverage, entry, sl, tp1, tp2, tp3, "
    "success_pct, budget_usd, notional_usd, qty, eta_sl, eta_tp1, eta_tp2, eta_tp3, reason, skip. "
    "If no trade, set skip=true and still return the JSON with symbol."
)

def gpt_user_prompt(symbol: str, tz: str) -> str:
    # נשמר קצר ומובנה כדי לחסוך טוקנים
    return (
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

async def suggest_one(symbol: str) -> Optional[TradeSug]:
    try:
        resp = await oai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role":"system", "content": GPT_SYSTEM},
                {"role":"user",   "content": gpt_user_prompt(symbol, TZ)}
            ],
            temperature=0.2,
            response_format={"type":"json_object"},
        )
        raw = resp.choices[0].message.content
        obj = json.loads(raw)
        sug = TradeSug.from_json(obj)
        if not sug.symbol:  # fallback
            sug.symbol = symbol
        if sug.skip:
            return None
        return sug
    except Exception as e:
        print(f"[WARN] GPT failed for {symbol}: {e}")
        return None

# === Gating helpers ===
_last_sent_ts: Dict[str, float] = {}        # cooldown per symbol
_last_hash_ts: Dict[tuple, float] = {}      # dedup window

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
    # Anchor שלך
    anchor = evaluate_anchor(sug.side, ANCHOR_MODE)

    # Quality שלך (בלי ATR כדי להישאר “דק” כאן)
    q = compute_quality(
        symbol=sug.symbol, side=sug.side,
        entry=sug.entry, sl=sug.sl, tp=sug.tp1,
        leverage=sug.leverage, budget=float(sug.budget_usd or 100.0),
        anchor=anchor, atr=None,
    )

    rr = rr_val(sug.entry, sug.sl, sug.tp1)
    dist = entry_dist_pct(sug)
    sp = float(sug.success_pct or 0.0)

    # סדר בדיקות (קשיח)
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

def kb_for_message(trade_id: str) -> Optional[Dict[str, Any]]:
    return (kb_inline(trade_id) if USE_INLINE_BUTTONS else None)

async def fetch_topk_from_core() -> Optional[List[str]]:
    if not CORE_TOPK_URL:
        return None
    try:
        headers = {"Authorization": f"Bearer {CORE_TOPK_TOKEN}"} if CORE_TOPK_TOKEN else {}
        async with httpx.AsyncClient(timeout=8) as client:
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
    if syms:  # Top-K אמיתי מה-Core (מומלץ)
        return syms[:TOPK_PER_SWEEP]
    # רוטציה קלה מה־pool שלך – כדי לא “לשרוף” על כולם כל פעם
    base = SUGGEST_SYMBOLS.copy()
    random.shuffle(base)
    return base[:TOPK_PER_SWEEP]

async def loop_forever():
    sem = asyncio.Semaphore(OPENAI_MAX_CONCURRENCY)
    sent_lock = asyncio.Lock()  # הגנה אם תרצה תקרה לסבב
    while True:
        chosen = await choose_symbols_for_sweep()
        print(f"[*] Sweep start | candidates={len(chosen)} | cap={MAX_TRADES_PER_SWEEP or '∞'} | interval={TRADE_SUGGEST_INTERVAL}m")

        sent = 0
        start = time.time()

        async def run_symbol(sym: str):
            nonlocal sent
            # אם יש תקרה לסבב
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
                # תקרה לסבב (אם קיימת)
                async with sent_lock:
                    if MAX_TRADES_PER_SWEEP and (sent >= MAX_TRADES_PER_SWEEP):
                        return
                    sent += 1
                trade_id = uuid.uuid4().hex[:8]
                text = format_msg(sug, trade_id)
                kb = kb_for_message(trade_id)
                try:
                    await tg_send(text, kb)
                    mark_sent(sug.symbol)
                    mark_hash(sug)
                    print(f"[OK] Alert sent: {sym} | id={trade_id} | sent={sent}")
                except Exception as e:
                    print(f"[ERR] Telegram send failed for {sym}: {e}")

        await asyncio.gather(*[run_symbol(s) for s in chosen])

        took = time.time() - start
        sleep_sec = max(5, TRADE_SUGGEST_INTERVAL*60 - int(took))
        print(f"[*] Sweep done in {took:.1f}s → sleeping {sleep_sec}s")
        await asyncio.sleep(sleep_sec)

if __name__ == "__main__":
    asyncio.run(loop_forever())

