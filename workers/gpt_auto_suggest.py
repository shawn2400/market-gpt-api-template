# workers/gpt_auto_suggest.py
from __future__ import annotations
import os, json, time, asyncio, hashlib, logging, random
from typing import Dict, Any, List, Optional, Tuple

import httpx
from openai import OpenAI

from utils.watchlist_utils import load_watchlist, build_symbol_pool, is_top10
from utils.hmac_utils import build_signed_outbound, generate_idempotency_key
from utils.redis_client import redis_client as RED
from utils.hours_profile import hours_profile_now
from utils.risk_rules import gate_trade, rr_from_levels, entry_gap_ok

# Grid helper
try:
    from utils.grid_builder import build_grid_plan
except Exception:
    build_grid_plan = None

# Funding bias (אופציונלי)
try:
    from utils.funding_bias import funding_bias_for_symbol  # returns float in [-1,1], positive favors LONG
except Exception:
    def funding_bias_for_symbol(symbol: str) -> float:
        return 0.0

# Liquidity gate — אם אין פונקציה ייעודית, נשתמש בהערכת סליפג' בסיסית
def _liquidity_gate_safe():
    try:
        from utils.liquidity import liquidity_gate  # type: ignore
        return liquidity_gate
    except Exception:
        try:
            from utils.liquidity import estimate_slippage  # fallback
        except Exception:
            estimate_slippage = None
        MAX_SLIPPAGE_PCT = float(os.getenv("MAX_SLIPPAGE_PCT", "0.30"))  # עד 0.30% דיפולט
        async def _fallback(symbol: str, side: str, notional_usd: float) -> Dict[str, Any]:
            if estimate_slippage is None:
                return {"ok": True}  # אין יכולת לבדוק — נאשר
            try:
                r = await estimate_slippage(symbol, side, notional_usd)
                if not r.get("ok"):
                    return {"ok": False, "reason": r.get("error","slippage-failed")}
                return {"ok": (float(r["slippage_pct"]) <= MAX_SLIPPAGE_PCT),
                        "slippage_pct": r["slippage_pct"]}
            except Exception as e:
                return {"ok": True, "reason": f"slip-fallback:{e}"}  # לא נחסום
        return _fallback

liquidity_gate_safe = _liquidity_gate_safe()

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
POOL_PER_CYCLE    = int(os.getenv("SYMBOLS_PER_CYCLE","10"))
MAX_CONCURRENCY   = int(os.getenv("OPENAI_MAX_CONCURRENCY","2"))
CAP_PER_CYCLE_ENV = int(os.getenv("SUGGEST_CAP_PER_CYCLE","5"))

SUCCESS_PCT_MIN   = float(os.getenv("SUCCESS_PCT_MIN","70"))

BUDGET_USD        = float(os.getenv("MAX_TRADE_BUDGET","100"))

# סוגי הצעות להפעלה
SUGGEST_FUTURES   = os.getenv("SUGGEST_FUTURES","1").lower() in ("1","true","yes")
SUGGEST_SPOT      = os.getenv("SUGGEST_SPOT","0").lower() in ("1","true","yes")
SUGGEST_GRID      = os.getenv("SUGGEST_GRID","0").lower() in ("1","true","yes")

DEFAULT_INTERVAL  = os.getenv("DEFAULT_INTERVAL","15m")

MIN_RR_TOP10 = float(os.getenv("MIN_RR_TOP10", "1.6"))
MIN_RR_ALT   = float(os.getenv("MIN_RR_ALT", "1.9"))

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

def _pass_cooldown_dyn(symbol: str, ttype: str, ttl_sec: int) -> bool:
    if RED:
        k = _cooldown_key(symbol, ttype)
        if RED.get(k):
            return False
        RED.setex(k, ttl_sec, "1")
        return True
    return True

def _pass_dedup(h: str, ttl_sec: int) -> bool:
    if RED:
        k = _dedup_key(h)
        if RED.get(k):
            return False
        RED.setex(k, ttl_sec, "1")
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

# ---------------- Proposers ----------------
def _min_rr_for(symbol: str, ctx_filters: Dict[str, Any]) -> float:
    # אם קיים min_rr מה-Context – נשתמש בו; אחרת Top10/Alt
    if ctx_filters and isinstance(ctx_filters.get("min_rr"), (int, float)):
        return float(ctx_filters["min_rr"])
    return MIN_RR_TOP10 if is_top10(symbol) else MIN_RR_ALT

def _apply_funding_bias_req(side: str, symbol: str, min_rr: float, success_min: float) -> Tuple[float, float, str]:
    fb = float(funding_bias_for_symbol(symbol))
    reason = ""
    # fb>0 → תומך LONG; fb<0 → תומך SHORT
    opposed = (side=="LONG" and fb < 0) or (side=="SHORT" and fb > 0)
    aligned = (side=="LONG" and fb > 0) or (side=="SHORT" and fb < 0)
    if opposed:
        # החמרה קלה
        min_rr += min(0.25, 0.2 * abs(fb))
        success_min += min(5.0, 10.0 * abs(fb))
        reason = f"funding_opposed({fb:+.2f})"
    elif aligned:
        min_rr -= min(0.15, 0.15 * abs(fb))
        success_min -= min(3.0, 6.0 * abs(fb))
        success_min = max(55.0, success_min)
        min_rr = max(1.3, min_rr)
        reason = f"funding_aligned({fb:+.2f})"
    return (min_rr, success_min, reason)

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
        if for_spot and side != "LONG":  # SPOT always LONG
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
        if prop["entry"] is None or prop["sl"] is None or prop["tp1"] is None:
            return None
        return prop
    except Exception as e:
        LOGGER.warning("gpt error %s", e)
        return None

async def propose_futures(symbol: str, ctx: Dict[str, Any], success_floor: float) -> Optional[Dict[str, Any]]:
    prop = await _gpt_suggest(symbol, ctx, for_spot=False)
    if not prop: return None

    price = (ctx or {}).get("price")
    if not entry_gap_ok(price, prop["entry"]):  # לא לרדוף
        return None

    # דרישת RR דינמית
    rr = rr_from_levels(prop["entry"], prop["sl"], prop["tp1"])
    min_rr = _min_rr_for(symbol, (ctx or {}).get("filters") or {})
    min_rr, success_req, fb_note = _apply_funding_bias_req(prop["side"], symbol, min_rr, success_floor)
    if rr is None or rr < min_rr:
        return None

    # גייטינג כללי
    vol_reg = ((ctx.get("filters") or {}).get("vol_regime","mid")) if ctx else "mid"
    g = gate_trade(symbol, prop["side"], price, prop["entry"], prop["sl"], prop["tp1"],
                   vol_regime=vol_reg, success_pct=prop.get("success_pct"), leverage=prop.get("leverage"))
    if not g["ok"]: return None

    if (prop.get("success_pct") or 0) < success_req:  # סף הצלחה דינמי
        return None

    # נזילות (סליפג') לנוטיונל ≈ budget*lev
    notional = float(BUDGET_USD) * float(prop.get("leverage") or 10)
    lg = await liquidity_gate_safe(symbol, prop["side"], notional_usd=notional)
    if not (lg.get("ok") if isinstance(lg, dict) else lg):
        return None

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
        "reason": (prop.get("reason") or "") + (f" [{fb_note}]" if fb_note else ""),
        "leverage": int(prop.get("leverage") or 10),
        "budget_usd": float(BUDGET_USD),
        "notional_usd": float(notional),
        "qty": None,
        "chat_id": TELEGRAM_CHAT_ID or None,
    }
    return payload

async def propose_spot(symbol: str, ctx: Dict[str, Any], success_floor: float) -> Optional[Dict[str, Any]]:
    prop = await _gpt_suggest(symbol, ctx, for_spot=True)
    if not prop: return None
    price = ctx.get("price") if ctx else None
    if not entry_gap_ok(price, prop["entry"]):
        return None

    rr = rr_from_levels(prop["entry"], prop["sl"], prop["tp1"])
    min_rr = _min_rr_for(symbol, (ctx or {}).get("filters") or {})
    # SPOT תמיד LONG; funding חיובי עוזר, שלילי מחמיר
    min_rr, success_req, fb_note = _apply_funding_bias_req("LONG", symbol, min_rr, success_floor)

    if rr is None or rr < min_rr:
        return None
    if (prop.get("success_pct") or 0) < success_req:
        return None

    # נזילות לנוטיונל = budget בלבד
    lg = await liquidity_gate_safe(symbol, "LONG", notional_usd=BUDGET_USD)
    if not (lg.get("ok") if isinstance(lg, dict) else lg):
        return None

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
        "reason": (prop.get("reason") or "") + " [SPOT]" + (f" [{fb_note}]" if fb_note else ""),
        "leverage": 1,
        "budget_usd": float(BUDGET_USD),
        "notional_usd": float(BUDGET_USD),
        "qty": None,
        "chat_id": TELEGRAM_CHAT_ID or None,
    }
    return payload

async def propose_grid(symbol: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if build_grid_plan is None:
        return None
    price = ctx.get("price") if ctx else None
    flags = (ctx.get("filters") or {}) if ctx else {}
    plan = build_grid_plan(symbol=symbol, price=price, flags=flags, budget_usd=BUDGET_USD)
    if not plan:
        return None

    # נזילות לנוטיונל ≈ budget (גריד לא ממונף כאן)
    lg = await liquidity_gate_safe(symbol, plan["grid_side"], notional_usd=BUDGET_USD)
    if not (lg.get("ok") if isinstance(lg, dict) else lg):
        return None

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
    # פרופיל שעות → קובע topK, cooldown, rr_bonus (rr_bonus כבר טופל ב-Context)
    hp = hours_profile_now()
    topk = max(1, int(hp.get("topk", 12)))
    cooldown_min = max(3, int(hp.get("cooldown_min", 12)))
    cooldown_sec = cooldown_min * 60

    # בנה Pool חכם (משקלול איכות+היסטוריית winrate)
    try:
        pool_syms = build_symbol_pool(k=topk, min_quality=6, include_anchor=True, include_shorts=True, balanced=True)
    except Exception:
        wl = load_watchlist(min_quality=None)
        pool_syms = [it["symbol"] for it in wl if it.get("symbol")] or ["BTCUSDT","ETHUSDT"]

    # שמור על POOL_PER_CYCLE אם ביקשת ספציפית
    random.shuffle(pool_syms)
    symbols = pool_syms[:max(1, min(POOL_PER_CYCLE, len(pool_syms)))]

    # Context batch
    ctx_map = {}
    try:
        ctx_map = await _fetch_context_batch(symbols, interval=DEFAULT_INTERVAL)
    except Exception as e:
        LOGGER.warning("context batch failed: %s", e)
        ctx_map = {}

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    accepted = 0
    # קאפ דינמי — ניקח המינימום בין env לבין topk/3 כדי לא להציף
    cap_per_cycle = max(1, min(CAP_PER_CYCLE_ENV, max(1, topk // 3)))

    async def maybe_emit(ttype: str, payload: Optional[Dict[str, Any]]):
        nonlocal accepted
        if not payload or accepted >= cap_per_cycle:
            return
        # Cooldown per (symbol,type)
        if not _pass_cooldown_dyn(payload["symbol"], ttype, cooldown_sec):
            return
        # Dedup (24h)
        dedup_ttl = int(float(os.getenv("DEDUP_TTL_SEC","86400")))
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
        if not _pass_dedup(h, dedup_ttl):
            return
        ok = await _emit(payload)
        if ok:
            accepted += 1

    async def handle_symbol(sym: str):
        ctx = ctx_map.get(sym) or {}
        success_floor = SUCCESS_PCT_MIN
        # לכל סימבול ייתכן התאמת funding ב-proposers

        # FUTURES
        if SUGGEST_FUTURES and accepted < cap_per_cycle:
            p = await propose_futures(sym, ctx, success_floor)
            await maybe_emit("FUTURES", p)
        # SPOT
        if SUGGEST_SPOT and accepted < cap_per_cycle:
            p = await propose_spot(sym, ctx, success_floor)
            await maybe_emit("SPOT", p)
        # GRID
        if SUGGEST_GRID and accepted < cap_per_cycle:
            p = await propose_grid(sym, ctx)
            await maybe_emit("GRID", p)

    async def worker(sym: str):
        async with sem:
            await handle_symbol(sym)

    await asyncio.gather(*(worker(s) for s in symbols))

async def main():
    if not SUGGEST_ENABLED:
        LOGGER.warning("Auto-suggest disabled (TRADE_AUTO_SUGGEST=0)")
    interval_sec = int(float(os.getenv("SUGGEST_INTERVAL_SEC","600")))   # 10m דיפולט
    while True:
        try:
            if SUGGEST_ENABLED:
                await process_cycle()
            await asyncio.sleep(interval_sec)
        except Exception as e:
            LOGGER.exception("cycle error: %s", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())















