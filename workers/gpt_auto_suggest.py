# workers/gpt_auto_suggest.py
from __future__ import annotations
import os, json, asyncio, time, uuid
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

# === ENV ===
load_dotenv(override=False)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o").strip()
SUGGEST_SYMBOLS = [s.strip().upper() for s in os.getenv("SUGGEST_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]
TRADE_SUGGEST_INTERVAL = int(os.getenv("TRADE_SUGGEST_INTERVAL", "10"))  # minutes
OPENAI_MAX_CONCURRENCY = int(os.getenv("OPENAI_MAX_CONCURRENCY", "2"))
TZ = os.getenv("TZ", "Asia/Jerusalem")

# --- Telegram (שליחה ישירה – לא תלוי main) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()
USE_INLINE_BUTTONS = (os.getenv("USE_INLINE_BUTTONS", "0").lower() in ("1","true","yes"))  # בלי webhook? עדיף 0

# === Fail fast checks ===
if not OPENAI_API_KEY:
    raise SystemExit("OPENAI_API_KEY missing")
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise SystemExit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing")

# === OpenAI client (v1.37.0) ===
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

# === פלט מה-GPT (JSON) ===
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
        # ערכי ברירת מחדל עדינים
        def f(name, default=None): return obj.get(name, default)
        return cls(
            symbol=str(f("symbol","")).upper(),
            side=str(f("side","")).upper(),
            current_price=float(f("current_price", 0.0)),
            leverage=int(f("leverage", 10)),
            entry=float(f("entry", 0.0)),
            sl=float(f("sl", 0.0)),
            tp1=float(f("tp1", 0.0)),
            tp2=(float(f("tp2")) if f("tp2") is not None else None),
            tp3=(float(f("tp3")) if f("tp3") is not None else None),
            success_pct=(float(f("success_pct")) if f("success_pct") is not None else None),
            budget_usd=(float(f("budget_usd")) if f("budget_usd") is not None else None),
            notional_usd=(float(f("notional_usd")) if f("notional_usd") is not None else None),
            qty=(float(f("qty")) if f("qty") is not None else None),
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
    # כאן בכוונה לא שולפים דאטה “חיצוני” – אתה יכול להחליף לנתונים משלך אם תרצה.
    # אם יש לך DataFeed פנימי – תעביר לכאן תקציר (RSI/ADX/ATR/מחיר נוכחי וכו׳).
    return (
        f"Generate a SINGLE futures trade idea for {symbol} (Binance), timeframe 15m.\n"
        f"Assume current market conditions as of now in timezone {tz}. "
        f"Return a JSON with the schema above. "
        f"- side ∈ {{LONG, SHORT}}\n"
        f"- leverage default 10 if unknown\n"
        f"- entry/sl/tp1/tp2/tp3 in price units\n"
        f"- success_pct (0-100)\n"
        f"- budget_usd if meaningful (e.g., 50 or 100)\n"
        f"- notional_usd = budget_usd * leverage (optional)\n"
        f"- qty approximate if possible\n"
        f"- eta_* strings in 'YYYY-MM-DD HH:MM' {tz}\n"
        f"- reason: 1-2 lines (why)\n"
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
        if not sug.symbol:
            sug.symbol = symbol
        if sug.skip:
            return None
        return sug
    except Exception as e:
        print(f"[WARN] GPT failed for {symbol}: {e}")
        return None

async def loop_forever():
    sem = asyncio.Semaphore(OPENAI_MAX_CONCURRENCY)
    while True:
        start = time.time()
        print(f"[*] Sweep start | symbols={len(SUGGEST_SYMBOLS)} | interval={TRADE_SUGGEST_INTERVAL}m")

        async def run_symbol(sym: str) -> None:
            async with sem:
                sug = await suggest_one(sym)
                if not sug:
                    return
                trade_id = uuid.uuid4().hex[:8]
                text = format_msg(sug, trade_id)
                kb = (kb_inline(trade_id) if USE_INLINE_BUTTONS else None)
                try:
                    await tg_send(text, kb)
                    print(f"[OK] Alert sent: {sym} | {trade_id}")
                except Exception as e:
                    print(f"[ERR] Telegram send failed for {sym}: {e}")

        await asyncio.gather(*[run_symbol(s) for s in SUGGEST_SYMBOLS])

        took = time.time() - start
        sleep_sec = max(5, TRADE_SUGGEST_INTERVAL*60 - int(took))
        print(f"[*] Sweep done in {took:.1f}s → sleeping {sleep_sec}s")
        await asyncio.sleep(sleep_sec)

if __name__ == "__main__":
    asyncio.run(loop_forever())
