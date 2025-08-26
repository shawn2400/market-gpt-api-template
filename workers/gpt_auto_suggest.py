# workers/gpt_auto_suggest.py
from __future__ import annotations
import os, json, time, asyncio, hashlib, logging, random
from typing import Dict, Any, List, Optional

import httpx
from openai import OpenAI

from utils.watchlist_utils import load_watchlist
from utils.hmac_utils import build_signed_outbound, generate_idempotency_key
from utils.redis_client import redis_client as RED
from utils.liquidity import liquidity_gate
from utils.risk_rules import (
    gate_trade, rr_from_levels, entry_gap_ok
)
from utils.grid_builder import build_grid_plan  # חדש

# ---------------- Config ----------------
LOGGER = logging.getLogger("gpt_auto_suggest")
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO").upper())

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY","").strip()
OPENAI_MODEL   = os.getenv("OPENAI_MODEL","gpt-4o").strip()

CONTEXT_URL = os.getenv("CONTEXT_URL","").strip()  # למשל: https://your-host
ALERT_INGEST_URL = os.getenv("ALERT_INGEST_URL","http://127.0.0.1:8000/alerts/trade-ingest").strip()
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET","").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", os.getenv("ADMIN_CHAT_ID","")).strip()

SUGGEST_ENABLED   = os.getenv("TRADE_AUTO_SUGGEST","0").lower() in ("1","true","yes")
INTERVAL_SEC      = int(float(os.getenv("SUGGEST_INTERVAL_SEC","600")))   # 10m
POOL_PER_CYCLE    = int(os.getenv("SYMBOLS_PER_CYCLE","10"))
MAX_CONCURRENCY   = int(os.getenv("OPENAI_MAX_CONCURRENCY","2"))
CAP_PER_CYCLE     = int(os.getenv("SUGGEST_CAP_PER_CYCLE","5"))

SUCCESS_PCT_MIN   = float(os.getenv("SUCCESS_PCT_MIN","70"))
COOLDOWN_SEC      = int(float(os.getenv("COOLDOWN_PER_SYMBOL_SEC","1800")))  # 30m
DEDUP_TTL_SEC     = int(float(os.getenv("DEDUP_TTL_SEC","86400")))           # 24h

BUDGET_USD        = float(os.getenv("MAX_TRADE_BUDGET","100"))

# סוגי הצעות להפעלה
SUGGEST_FUTURES   = os.getenv("SUGGEST_FUTURES","1").lower() in ("1","true","yes")
SUGGEST_SPOT      = os.getenv("SUGGEST_SPOT","0").lower() in ("1","true","yes")
SUGGEST_GRID      = os.getenv("SUGGEST_GRID","0").lower() in ("1","true","yes")

DEFAULT_INTERVAL  = os.getenv("DEFAULT_INTERVAL","15m")

# ---------------- Helpers ----------------
def _hash_proposal(key_fields: Dict[str, Any]) -> str:
    key = f"{key_fields.get('trade_type','')}|{key_fields.get('symbol','')}|{key_fields.get('side','')}|" \
          f"{key_fields.get('entry')}|{key_fields.get('sl')}|{key_fields.get('tp1')}|{key_fields.get('tp2')}|{key_fields.get('tp3')}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

async def _fetch_context_batch(symbols: List[str], interval: str = DEFAULT_INTERVAL) -> Dict[str, Dict[str, Any]]:
    if not CONTEXT_URL:
        LOGGER.warning("CONTEXT_URL not set – worker running without context (reduced gating).")
        return {}
    payload = {"symbols": symbols, "interval": interval, "compact": True}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(CONTEXT_URL.rstrip("/") + "/context/batch", json=payload)
        r.raise_for_status()
        out = {}
        for it in r.json().get("items", []):
            out[it["symbol"]] = it
        return out

def _cooldown_key(symbol: str, ttype: str) -> str:
    return f"algogpt:cooldown:{ttype}:{symbol.upper()}"

def _dedup_key(h: str) -> str:
    return f"algogpt:dedup:{h}"

def _pass_cooldown(symbol: str, ttype: str) -> bool:
    if RED:
        k = _cooldown_key(symbol, ttype)
        if RED.get(k):
            return False
        RED.setex(k, COOLDOWN_SEC, "1")
        return True
    return True

def _pass_dedup(h: str) -> bool:
    if RED:
        k = _dedup_key(h)
        if RED.get(k):
            return False
        RED.setex(k, DEDUP_TTL_SEC, "1")
        return True
    return True

# ---------------- GPT ----------------
_client: Optional[OpenAI] = None
def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client

PROMPT_SYS = (
    "You are a crypto trading assistant.\n"
    "You will receive compact market context: current price and boolean/enum filters.\n"
    "Return ONLY JSON with fields:\n"
    "  side ('LONG'|'SHORT'), entry, sl, tp1, tp2, tp3, leverage (int), success_pct (0..100), reason (short).\n"
    "Rules:\n"
    "- Respect trend flags and avoid chop (danger_chop).\n"
    "- Do NOT chase far from price; use nearby logical pullbacks/breakouts.\n"
    "- Favor RR>=1.6 when reasonable.\n"
)

PROMPT_SYS_SPOT = PROMPT_SYS + "This request is for SPOT trading. side must be 'LONG'. leverage MUST be 1.\n"
PROMPT_SYS_FUT  = PROMPT_SYS + "This request is for FUTURES trading. side can be LONG or SHORT.\n"

def _build_user_ctx(symbol: str, ctx: Dict[str, Any]) -> str:
    data = {"symbol": symbol, "price": ctx.get("price"), "filters": ctx.get("filters", {})}
    return json.dumps(data, ensure_ascii=False)

def _parse_json_safe(text: str) -> Optional[Dict[str, Any]]:
    try: return json.loads(text)
    except Exception: return None

async def _gpt_suggest(symbol: str, ctx: Dict[str, Any], for_spot: bool) -> Optional[Dict[str, Any]]:
    if not OPENAI_API_KEY:
        LOGGER.error("OPENAI_API_KEY missing")
        return None
    cli = _get_client()
    sys_prompt = PROMPT_SYS_SPOT if for_spot else PROMPT_SYS_FUT
    user = _build_user_ctx(symbol, ctx or {})
    try:
        resp = cli.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role":"system","content":sys_prompt},{"role":"user","content":user}],
            temperature=0.2,
            max_tokens=300,
            response_format={"type":"json_object"},
        )
        content = resp.choices[0].message.content
        data = _parse_json_safe(content) or {}
        side = str(data.get("side","")).upper()
        if for_spot and side != "LONG":  # הגנת SPOT
            side = "LONG"
        prop = {
            "symbol": symbol,
            "side": side if side in ("LONG","SHORT") else None,
            "entry": _to_float(data.get("entry")),
            "sl": _to_float(data.get("sl")),
            "tp1": _to_float(data.get("tp1")),
            "tp2": _to_float(data.get("tp2")),
            "tp3": _to_float(data.get("tp3")),
            "leverage": (1 if for_spot else _to_int(data.get("leverage"), default=10)),
            "success_pct": _to_float(data.get("success_pct")),
            "reason": data.get("reason") or "",
        }
        if prop["side"] not in ("LONG","SHORT"):
            return None
        # חובה: entry/sl/tp1
        if prop["entry"] is None or prop["sl"] is None or prop["tp1"] is None:
            return None
        return prop
    except Exception as e:
        LOGGER.warning("gpt error %s", e)
        return None

def _to_float(x) -> Optional[float]:
    try:
        v = float(x)
        if v == v and v not in (float("inf"), float("-inf")):
            return v
    except Exception:
        pass
    return None

def _to_int(x, default=None) -> Optional[int]:
    try: return int(x)
    except Exception: return default

# ---------------- Emit ----------------
async def _emit(payload: Dict[str, Any]) -> bool:
    if not WEBHOOK_HMAC_SECRET:
        LOGGER.error("WEBHOOK_HMAC_SECRET not set")
        return False
    body, headers = build_signed_outbound(
        WEBHOOK_HMAC_SECRET, payload,
        idempotency_key=generate_idempotency_key(),
        extra_headers={"Content-Type":"application/json"},
    )
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(ALERT_INGEST_URL, content=body, headers=headers)
        r.raise_for_status()
        return True

# ---------------- Per-type pipelines ----------------
async def propose_futures(symbol: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    prop = await _gpt_suggest(symbol, ctx, for_spot=False)
    if not prop: return None

    price = ctx.get("price")
    if not entry_gap_ok(price, prop["entry"]):  # לא לרדוף
        return None

    # גייטינג כללי (RR/lev-cap לפי vol_regime)
    vol_reg = (ctx.get("filters") or {}).get("vol_regime","mid")
    g = gate_trade(symbol, prop["side"], price, prop["entry"], prop["sl"], prop["tp1"],
                   vol_regime=vol_reg, success_pct=prop.get("success_pct"), leverage=prop.get("leverage"))
    if not g["ok"]: return None
    if (prop.get("success_pct") or 0) < SUCCESS_PCT_MIN: return None

    # נזילות (סליפג') לנוטיונל ≈ budget*lev
    notional = float(BUDGET_USD) * float(prop.get("leverage") or 10)
    lg = liquidity_gate(symbol, prop["side"], notional_usd=notional)
    if not lg.get("ok"): return None

    payload = {
        "trade_id": f"f{int(time.time())}{random.randint(100,999)}",
        "trade_type": "FUTURES",
        "symbol": symbol,
        "side": prop["side"],
        "current_price": float(price or 0.0),
        "entry": float(prop["entry"]), "sl": float(prop["sl"]),
        "tp1": float(prop["tp1"]),
        "tp2": float(prop["tp2"]) if prop.get("tp2") else None,
        "tp3": float(prop["tp3"]) if prop.get("tp3") else None,
        "success_pct": float(prop.get("success_pct") or 0.0),
        "reason": prop.get("reason") or "",
        "leverage": int(prop.get("leverage") or 10),
        "budget_usd": float(BUDGET_USD),
        "notional_usd": float(notional),
        "qty": None,
        "chat_id": TELEGRAM_CHAT_ID or None,
    }
    return payload

async def propose_spot(symbol: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    prop = await _gpt_suggest(symbol, ctx, for_spot=True)
    if not prop: return None
    price = ctx.get("price")
    if not entry_gap_ok(price, prop["entry"]):  # לא לרדוף
        return None
    # SPOT: אין מינוף; גייטינג RR בלבד
    g = gate_trade(symbol, "LONG", price, prop["entry"], prop["sl"], prop["tp1"],
                   vol_regime=(ctx.get("filters") or {}).get("vol_regime","mid"),
                   success_pct=prop.get("success_pct"), leverage=1)
    if not g["ok"]: return None
    if (prop.get("success_pct") or 0) < SUCCESS_PCT_MIN: return None

    # נזילות לנוטיונל = budget בלבד
    lg = liquidity_gate(symbol, "LONG", notional_usd=BUDGET_USD)
    if not lg.get("ok"): return None

    payload = {
        "trade_id": f"s{int(time.time())}{random.randint(100,999)}",
        "trade_type": "SPOT",
        "symbol": symbol,
        "side": "LONG",
        "current_price": float(price or 0.0),
        "entry": float(prop["entry"]), "sl": float(prop["sl"]),
        "tp1": float(prop["tp1"]),
        "tp2": float(prop["tp2"]) if prop.get("tp2") else None,
        "tp3": float(prop["tp3"]) if prop.get("tp3") else None,
        "success_pct": float(prop.get("success_pct") or 0.0),
        "reason": (prop.get("reason") or "") + " [SPOT]",
        "leverage": 1,
        "budget_usd": float(BUDGET_USD),
        "notional_usd": float(BUDGET_USD),
        "qty": None,
        "chat_id": TELEGRAM_CHAT_ID or None,
    }
    return payload

async def propose_grid(symbol: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    price = ctx.get("price")
    flags = (ctx.get("filters") or {})
    plan = build_grid_plan(symbol=symbol, price=price, flags=flags, budget_usd=BUDGET_USD)
    if not plan:  # לא מתאים לגריד
        return None

    # נזילות לנוטיונל ≈ budget (גריד לא ממונף כאן)
    lg = liquidity_gate(symbol, plan["grid_side"], notional_usd=BUDGET_USD)
    if not lg.get("ok"): return None

    payload = {
        "trade_id": f"g{int(time.time())}{random.randint(100,999)}",
        "trade_type": "GRID",
        "symbol": symbol,
        "current_price": float(price or 0.0),
        "grid_min": float(plan["grid_min"]),
        "grid_max": float(plan["grid_max"]),
        "grid_levels": int(plan["grid_levels"]),
        "grid_step_pct": float(plan["grid_step_pct"]),
        "grid_take_profit_pct": float(plan["grid_take_profit_pct"]),
        "grid_side": plan["grid_side"],
        "reason": plan["reason"],
        "budget_usd": float(BUDGET_USD),
        "notional_usd": float(BUDGET_USD),
        "chat_id": TELEGRAM_CHAT_ID or None,
    }
    return payload

# ---------------- Cycle ----------------
async def process_cycle():
    wl = load_watchlist(min_quality=None)
    symbols = [it["symbol"] for it in wl if it.get("symbol")] or ["BTCUSDT","ETHUSDT","BNBUSDT"]
    random.shuffle(symbols)
    pool = symbols[:POOL_PER_CYCLE]

    ctx_map = await _fetch_context_batch(pool, interval=DEFAULT_INTERVAL)

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    accepted = 0

    async def maybe_emit(ttype: str, payload: Optional[Dict[str, Any]]):
        nonlocal accepted
        if not payload or accepted >= CAP_PER_CYCLE:
            return
        # Cooldown per (symbol,type)
        if not _pass_cooldown(payload["symbol"], ttype):
            return
        # Dedup
        h = _hash_proposal({
            "trade_type": ttype,
            "symbol": payload["symbol"],
            "side": payload.get("side"),
            "entry": payload.get("entry"),
            "sl": payload.get("sl"),
            "tp1": payload.get("tp1"),
            "tp2": payload.get("tp2"),
            "tp3": payload.get("tp3"),
        })
        if not _pass_dedup(h):
            return
        ok = await _emit(payload)
        if ok:
            accepted += 1

    async def handle_symbol(sym: str):
        ctx = ctx_map.get(sym) or {}
        # FUTURES
        if SUGGEST_FUTURES and accepted < CAP_PER_CYCLE:
            p = await propose_futures(sym, ctx)
            await maybe_emit("FUTURES", p)
        # SPOT
        if SUGGEST_SPOT and accepted < CAP_PER_CYCLE:
            p = await propose_spot(sym, ctx)
            await maybe_emit("SPOT", p)
        # GRID
        if SUGGEST_GRID and accepted < CAP_PER_CYCLE:
            p = await propose_grid(sym, ctx)
            await maybe_emit("GRID", p)

    async def worker(sym: str):
        async with sem:
            await handle_symbol(sym)

    await asyncio.gather(*(worker(s) for s in pool))

async def main():
    if not SUGGEST_ENABLED:
        LOGGER.warning("Auto-suggest disabled (TRADE_AUTO_SUGGEST=0)")
    while True:
        try:
            if SUGGEST_ENABLED:
                await process_cycle()
            await asyncio.sleep(INTERVAL_SEC)
        except Exception as e:
            LOGGER.exception("cycle error: %s", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())













