# workers/gpt_auto_suggest.py
from __future__ import annotations
import os, json, time, asyncio, hashlib, logging, random
from typing import Dict, Any, List, Optional, Tuple

import httpx
from openai import OpenAI

from utils.watchlist_utils import load_watchlist
from utils.hmac_utils import build_signed_outbound, generate_idempotency_key
from utils.redis_client import redis_client as RED
from utils.liquidity import liquidity_gate
from utils.risk_rules import (
    ensure_tp_sl_with_atr, gate_trade, rr_from_levels,
)

# ---------------- Config ----------------
LOGGER = logging.getLogger("gpt_auto_suggest")
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO").upper())

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY","").strip()
OPENAI_MODEL   = os.getenv("OPENAI_MODEL","gpt-4o").strip()

# Context endpoint (FastAPI שלך)
CONTEXT_URL = os.getenv("CONTEXT_URL","").strip()  # למשל: https://your-host/context/batch

# היכן לשגר את ההתרעה (ה-tele sink שלך)
ALERT_INGEST_URL = os.getenv("ALERT_INGEST_URL","http://127.0.0.1:8000/alerts/trade-ingest").strip()
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET","").strip()

# טלגרם (רק לצורך chat_id יעד)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", os.getenv("ADMIN_CHAT_ID","")).strip()

# מחזוריות
SUGGEST_ENABLED = os.getenv("TRADE_AUTO_SUGGEST","0").lower() in ("1","true","yes")
INTERVAL_SEC    = int(float(os.getenv("SUGGEST_INTERVAL_SEC","600")))  # ברירת מחדל 10 דקות
POOL_PER_CYCLE  = int(os.getenv("SYMBOLS_PER_CYCLE","10"))
MAX_CONCURRENCY = int(os.getenv("OPENAI_MAX_CONCURRENCY","2"))
CAP_PER_CYCLE   = int(os.getenv("SUGGEST_CAP_PER_CYCLE","5"))

# סינון/גייטינג
SUCCESS_PCT_MIN = float(os.getenv("SUCCESS_PCT_MIN","70"))
COOLDOWN_SEC    = int(float(os.getenv("COOLDOWN_PER_SYMBOL_SEC","1800")))  # 30 דקות
DEDUP_TTL_SEC   = int(float(os.getenv("DEDUP_TTL_SEC","86400")))
BUDGET_USD      = float(os.getenv("MAX_TRADE_BUDGET","100"))

# זמן מקומי
LOCAL_TZ = os.getenv("LOCAL_TZ","Asia/Jerusalem")

# ---------------- Helpers ----------------
def _hash_proposal(p: Dict[str, Any]) -> str:
    key = f"{p.get('symbol','')}|{p.get('side','')}|{p.get('entry')}|{p.get('sl')}|{p.get('tp1')}|{p.get('tp2')}|{p.get('tp3')}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

async def _fetch_context_batch(symbols: List[str], interval: str = "15m") -> Dict[str, Dict[str, Any]]:
    if not CONTEXT_URL:
        LOGGER.warning("CONTEXT_URL not set – worker will not have indicators/filters (risk/liq gates reduced)")
        return {}
    payload = {"symbols": symbols, "interval": interval, "compact": True}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(_join(CONTEXT_URL, "/context/batch"), json=payload)
        r.raise_for_status()
        data = r.json()
        out = {}
        for item in data.get("items", []):
            out[item["symbol"]] = item
        return out

def _join(base: str, path: str) -> str:
    return base.rstrip("/") + path

def _cooldown_key(symbol: str) -> str:
    return f"algogpt:cooldown:{symbol.upper()}"

def _dedup_key(h: str) -> str:
    return f"algogpt:dedup:{h}"

def _now_ts() -> int:
    return int(time.time())

# ---------------- GPT ----------------
_client: Optional[OpenAI] = None
def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client

PROMPT_SYS = (
    "You are a crypto futures trading assistant. "
    "Input is compact context (price + filters). "
    "Return a single JSON with: side (LONG/SHORT), entry, sl, tp1, tp2, tp3, leverage (int), "
    "success_pct (0-100), reason (short). Use price-aware, do not chase far from current price. "
    "Respect general trend; avoid chop (danger_chop). Balance RR>=1.6 if possible. "
    "Output JSON only."
)

def _build_user_ctx(symbol: str, ctx: Dict[str, Any]) -> str:
    # נספק ל-GPT רק מה שצריך; RR/lev cap/liq נבדקים אצלנו (לא לבקש מגידור כפול).
    data = {
        "symbol": symbol,
        "price": ctx.get("price"),
        "filters": ctx.get("filters", {}),
        # שים לב: לא שולחים לו מינוף-קאפ/קיֵלי וכו' — זה אצלנו.
    }
    return json.dumps(data, ensure_ascii=False)

def _parse_json_safe(text: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(text)
    except Exception:
        return None

async def suggest_one(symbol: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    מחזיר הצעת טרייד מ-GPT בפורמט dict או None.
    """
    if not OPENAI_API_KEY:
        LOGGER.error("OPENAI_API_KEY missing")
        return None
    cli = _get_client()
    user = _build_user_ctx(symbol, ctx or {})
    try:
        resp = cli.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role":"system", "content": PROMPT_SYS},
                {"role":"user", "content": user},
            ],
            temperature=0.2,
            max_tokens=300,
            response_format={"type":"json_object"},
        )
        content = resp.choices[0].message.content
        data = _parse_json_safe(content) or {}
        # Normalize
        out = {
            "symbol": symbol,
            "side": str(data.get("side","")).upper() or None,
            "entry": _to_float(data.get("entry")),
            "sl": _to_float(data.get("sl")),
            "tp1": _to_float(data.get("tp1")),
            "tp2": _to_float(data.get("tp2")),
            "tp3": _to_float(data.get("tp3")),
            "leverage": _to_int(data.get("leverage"), default=10),
            "success_pct": _to_float(data.get("success_pct")),
            "reason": data.get("reason") or "",
        }
        if out["side"] not in ("LONG","SHORT"):
            return None
        return out
    except Exception as e:
        LOGGER.warning("gpt error %s", e)
        return None

def _to_float(x) -> Optional[float]:
    try:
        v = float(x)
        if v == v and v != float("inf") and v != float("-inf"):
            return v
    except Exception:
        pass
    return None

def _to_int(x, default=None) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return default

# ---------------- Gates (no double-work vs GPT) ----------------
def pass_success_threshold(p: Dict[str, Any]) -> bool:
    sp = p.get("success_pct")
    return (sp is not None) and (float(sp) >= SUCCESS_PCT_MIN)

def pass_cooldown(symbol: str) -> bool:
    if RED:
        key = _cooldown_key(symbol)
        if RED.get(key):
            return False
        RED.setex(key, COOLDOWN_SEC, "1")
        return True
    # local fallback: לא מתמיד בין אינסטנציות—מומלץ Redis
    return True

def pass_dedup(h: str) -> bool:
    if RED:
        key = _dedup_key(h)
        if RED.get(key):
            return False
        RED.setex(key, DEDUP_TTL_SEC, "1")
        return True
    return True

# ---------------- Emit to Telegram sink ----------------
async def emit_trade(proposal: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """
    שולח ל-/alerts/trade-ingest עם HMAC + Idempotency-Key.
    """
    if not WEBHOOK_HMAC_SECRET:
        LOGGER.error("WEBHOOK_HMAC_SECRET not set")
        return False

    price = ctx.get("price")
    vol_reg = (ctx.get("filters") or {}).get("vol_regime")

    # להשלים TP/SL אם חסרים, לפי ATR אם יש
    atr = None  # compact=1 לא מחזיר ATR; זה בכוונה (דל-עומס). נשאיר כמות-קיימת בלבד.
    # אם תרצה, תחליף ל-context מלא ותשלוף ATR:
    # atr = (ctx.get("ind") or {}).get("atr")

    # לא ניכר כאן ATR → אם GPT לא נתן SL/TP, לא נשלים “עיוור”; נחסום בהמשך gate_trade.
    levels = ensure_tp_sl_with_atr(
        proposal["side"], price, atr,
        proposal.get("entry"), proposal.get("sl"), proposal.get("tp1")
    )
    entry = levels["entry"]; sl = levels["sl"]; tp1 = levels["tp"]
    tp2 = proposal.get("tp2"); tp3 = proposal.get("tp3")

    rr = rr_from_levels(proposal["side"], entry, sl, tp1) if (entry and sl and tp1) else None

    # Gates: RR/lev cap/entry gap — ללא כפילות מול GPT
    g = gate_trade(
        proposal["symbol"], proposal["side"], price, entry, sl, tp1,
        vol_regime=(vol_reg or "mid"),
        success_pct=proposal.get("success_pct"),
        leverage=proposal.get("leverage"),
    )
    if not g["ok"]:
        LOGGER.info("gate_trade rejected %s: %s", proposal["symbol"], g["reasons"])
        return False

    # נזילות (סליפג’): notional≈budget*lev (FUTURES)
    notional = float(BUDGET_USD) * float(proposal.get("leverage") or 10)
    lg = liquidity_gate(proposal["symbol"], proposal["side"], notional_usd=notional)
    if not lg.get("ok"):
        LOGGER.info("liquidity_gate rejected %s: %s", proposal["symbol"], lg.get("reason"))
        return False

    payload = {
        "trade_id": f"g{int(time.time())}{random.randint(100,999)}",
        "trade_type": "FUTURES",          # כרגע worker מציע FUTURES; SPOT/GRID מופרדים
        "symbol": proposal["symbol"],
        "side": proposal["side"],
        "current_price": float(price or 0.0),
        "entry": float(entry or 0.0),
        "sl": float(sl or 0.0),
        "tp1": float(tp1 or 0.0),
        "tp2": float(tp2 or 0.0) if tp2 else None,
        "tp3": float(tp3 or 0.0) if tp3 else None,
        "success_pct": float(proposal.get("success_pct") or 0.0),
        "reason": proposal.get("reason") or "",
        "leverage": int(proposal.get("leverage") or 10),
        "budget_usd": float(BUDGET_USD),
        "notional_usd": float(notional),
        "qty": None,  # חישוב כמות נעשה בצד ה-Trade executor אם צריך
        "chat_id": TELEGRAM_CHAT_ID or None,
    }

    body, headers = build_signed_outbound(
        WEBHOOK_HMAC_SECRET, payload,
        idempotency_key=generate_idempotency_key(),
        extra_headers={"Content-Type":"application/json"},
    )
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(ALERT_INGEST_URL, content=body, headers=headers)
        r.raise_for_status()
        return True

async def process_cycle():
    wl = load_watchlist(min_quality=None)
    # בחר Pool לסבב: איכות גבוהה ראשונות + רוטציה קלה
    symbols = [it["symbol"] for it in wl if it.get("symbol")] or ["BTCUSDT","ETHUSDT","BNBUSDT"]
    random.shuffle(symbols)
    pool = symbols[:POOL_PER_CYCLE]

    ctx_map = await _fetch_context_batch(pool, interval=os.getenv("DEFAULT_INTERVAL","15m"))
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    accepted = 0

    async def handle_symbol(sym: str):
        nonlocal accepted
        # Cooldown per symbol (ב־Redis)
        if not pass_cooldown(sym):
            return

        ctx = ctx_map.get(sym) or {}
        prop = await suggest_one(sym, ctx)
        if not prop:
            return

        if not pass_success_threshold(prop):
            return

        # דה-דופליקציה
        h = _hash_proposal({
            "symbol": sym, "side": prop["side"],
            "entry": prop.get("entry"), "sl": prop.get("sl"),
            "tp1": prop.get("tp1"), "tp2": prop.get("tp2"), "tp3": prop.get("tp3"),
        })
        if not pass_dedup(h):
            return

        if accepted >= CAP_PER_CYCLE:
            return

        ok = await emit_trade(prop, ctx)
        if ok:
            accepted += 1

    async def worker(sym: str):
        async with sem:
            await handle_symbol(sym)

    await asyncio.gather(*(worker(s) for s in pool))

async def main():
    if not SUGGEST_ENABLED:
        LOGGER.warning("Auto-suggest is disabled (TRADE_AUTO_SUGGEST=0)")
    while True:
        try:
            if SUGGEST_ENABLED:
                await process_cycle()
            else:
                LOGGER.debug("sleep (disabled)")
            await asyncio.sleep(INTERVAL_SEC)
        except Exception as e:
            LOGGER.exception("cycle error: %s", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())












