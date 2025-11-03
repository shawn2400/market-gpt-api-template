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
from utils.budget import get_trade_budget_usdt  # ← תקציב דינמי
from utils.dynamic_filters import get_dynamic_thresholds, explain_filters  # ← סינונים דינמיים
from utils.market_intelligence import get_market_intelligence  # ← Market Intelligence Engine
from utils.adaptive_prompts import get_adaptive_prompt_engine  # ← Adaptive AI Prompts
from utils.portfolio_intelligence import get_portfolio_intelligence  # ← Portfolio Intelligence
from utils.performance_tracker import get_performance_tracker  # ← Performance Tracker
from utils.dynamic_sizing import get_dynamic_sizing_engine  # ← Dynamic Leverage & Position Sizing
from utils.flip_intelligence import get_flip_intelligence  # ← Position Flip Intelligence
from utils.resource_manager import get_resource_manager  # ← Smart Resource Management
from utils.multi_tf_manager import MultiTFContextManager  # ← Multi-Timeframe Context Manager
from utils.auto_flip import analyze_multi_tf_weighted  # ← Weighted Multi-TF Analysis
from utils.db import insert_tf_snapshot  # ← TF Snapshot Persistence
from utils.ai_tracker import log_prediction, MarketRegime, AIModel  # ← AI Performance Tracking

# Grid helper
try:
    from utils.grid_builder import build_grid_plan
except Exception:
    build_grid_plan = None

# Funding bias (אופציונלי)
async def funding_bias_for_symbol(symbol: str) -> float:
    """
    Wrapper async - מחזיר bias factor ∈ [-1,1].
    חיובי → favors LONG, שלילי → favors SHORT.
    """
    try:
        from utils.funding_bias import get_funding_rate, funding_bias_factor  # type: ignore
        rate = await get_funding_rate(symbol)
        return funding_bias_factor(rate, side=None)
    except Exception:
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
OPENAI_MODEL   = os.getenv("OPENAI_MODEL","gpt-5-2025-08-07").strip()

CONTEXT_URL = os.getenv("CONTEXT_URL","").strip()  # למשל: https://your-host
ALERT_INGEST_URL = os.getenv("ALERT_INGEST_URL","http://127.0.0.1:8000/alerts/trade-ingest").strip()
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET","").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", os.getenv("ADMIN_CHAT_ID","")).strip()

SUGGEST_ENABLED   = os.getenv("TRADE_AUTO_SUGGEST","0").lower() in ("1","true","yes")
POOL_PER_CYCLE    = int(os.getenv("SYMBOLS_PER_CYCLE","10"))
MAX_CONCURRENCY   = int(os.getenv("OPENAI_MAX_CONCURRENCY","2"))
CAP_PER_CYCLE_ENV = int(os.getenv("SUGGEST_CAP_PER_CYCLE","5"))

SUCCESS_PCT_MIN   = float(os.getenv("SUCCESS_PCT_MIN","70"))

# תקציב בסיס (ישמש כפולבק אם הדינמי כבוי)
BUDGET_USD_FALLBK = float(os.getenv("MAX_TRADE_BUDGET","100"))

# סוגי הצעות להפעלה
SUGGEST_FUTURES   = os.getenv("SUGGEST_FUTURES","1").strip().lower() in ("1","true","yes")
SUGGEST_SPOT      = os.getenv("SUGGEST_SPOT","0").strip().lower() in ("1","true","yes")
SUGGEST_GRID      = os.getenv("SUGGEST_GRID","0").strip().lower() in ("1","true","yes")

DEFAULT_INTERVAL  = os.getenv("DEFAULT_INTERVAL","15m")

MIN_RR_TOP10 = float(os.getenv("MIN_RR_TOP10", "1.01"))
MIN_RR_ALT   = float(os.getenv("MIN_RR_ALT", "1.01"))

# גג מינוף להצעות GPT (ביטחון)
SUGGEST_MAX_LEVERAGE = int(os.getenv("SUGGEST_MAX_LEVERAGE","10"))
SUGGEST_MIN_LEVERAGE = max(1, int(os.getenv("SUGGEST_MIN_LEVERAGE","1")))

# ---------------- Helpers ----------------
def _hash_proposal(key_fields: Dict[str, Any]) -> str:
    key = f"{key_fields.get('trade_type','')}|{key_fields.get('symbol','')}|{key_fields.get('side','')}|" \
          f"{key_fields.get('entry')}|{key_fields.get('sl')}|{key_fields.get('tp1')}|{key_fields.get('tp2')}|{key_fields.get('tp3')}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

async def _fetch_context_batch(
    symbols: List[str], 
    interval: str = DEFAULT_INTERVAL,
    intervals: Optional[List[str]] = None,
    use_multi_tf: bool = False
) -> Dict[str, Dict[str, Any]]:
    """
    Fetch context data for symbols.
    
    Args:
        symbols: List of symbols
        interval: Single interval (backward compatible)
        intervals: Multi-timeframe intervals (e.g., ["15m", "1h", "4h"])
        use_multi_tf: Enable multi-timeframe mode
        
    Returns:
        Dict mapping symbol -> context data
        If use_multi_tf=True, context includes "multi_tf" field with all timeframes
    """
    if not CONTEXT_URL:
        LOGGER.warning("CONTEXT_URL not set – worker running without context (reduced gating).")
        return {}
    
    payload = {"symbols": symbols, "interval": interval, "compact": True}
    
    # Add multi-TF support if enabled
    if use_multi_tf and intervals:
        payload["intervals"] = intervals
    
    # Get API key from environment for authentication
    api_key = os.getenv("API_BEARER_TOKEN") or os.getenv("PRIMARY_API_TOKEN") or os.getenv("API_TOKEN") or ""
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(CONTEXT_URL.rstrip("/") + "/context/batch", json=payload, headers=headers)
            r.raise_for_status()
            resp_data = r.json()
            
            out = {}
            
            # Single-TF mode (backward compatible)
            if not use_multi_tf or "multi_tf_items" not in resp_data:
                for it in resp_data.get("items", []):
                    out[it["symbol"]] = it
                return out
            
            # Multi-TF mode - combine multi_tf data with primary context
            for it in resp_data.get("items", []):
                out[it["symbol"]] = it
            
            # Add multi_tf data to each symbol's context
            for mt_item in resp_data.get("multi_tf_items", []):
                symbol = mt_item["symbol"]
                if symbol in out:
                    out[symbol]["multi_tf"] = mt_item.get("multi_tf", {})
            
            return out
    except Exception as e:
        LOGGER.warning("context batch failed: %s", e)
        return {}

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

def _quality_from_ctx(ctx: Dict[str, Any]) -> Optional[float]:
    flt = (ctx or {}).get("filters") or {}
    for k in ("quality", "quality_score", "q", "score"):
        v = flt.get(k)
        try:
            if v is None: 
                continue
            return float(v)
        except Exception:
            continue
    return None

def _maybe_float(d: Dict[str, Any], *keys: str) -> Optional[float]:
    for k in keys:
        v = d.get(k)
        try:
            if v is None: 
                continue
            return float(v)
        except Exception:
            continue
    return None

# ---------------- GPT ----------------
_client: Optional[OpenAI] = None
def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client

PROMPT_SYS = (
    "You are an expert crypto trading strategist focused on HIGH-QUALITY, HIGH-PROFIT trades.\n"
    "You will receive compact market context: current price and boolean/enum filters.\n"
    "Return ONLY JSON with fields:\n"
    "  side ('LONG'|'SHORT'), entry, sl, tp1, tp2, tp3, leverage (int), success_pct (0..100), reason (short).\n"
    "\n"
    "⚠️ MANDATORY: ALL TRADES **MUST** HAVE RR (Risk/Reward) ≥ 1.3 MINIMUM! ⚠️\n"
    "CRITICAL RULES (MUST FOLLOW):\n"
    "1. Risk/Reward (RR) calculation - **THIS IS MANDATORY**:\n"
    "   - RR = |entry - tp1| / |entry - sl|\n"
    "   - **MINIMUM RR = 1.3** (proposals with RR<1.3 will be AUTO-REJECTED)\n"
    "   - TARGET RR ≥ 1.5-2.0 for best results\n"
    "   \n"
    "   Examples:\n"
    "   ✓ GOOD: entry=100, sl=98 (-2%), tp1=103 (+3%) → RR=1.5 PASS\n"
    "   ✓ GREAT: entry=100, sl=98 (-2%), tp1=104 (+4%) → RR=2.0 PASS\n"
    "   ✗ BAD: entry=100, sl=98 (-2%), tp1=101.5 (+1.5%) → RR=0.75 REJECT\n"
    "   ✗ BAD: entry=100, sl=98 (-2%), tp1=102.4 (+2.4%) → RR=1.2 REJECT\n"
    "\n"
    "2. Entry placement:\n"
    "   - MUST be within 0.3-1.0% of current price (no far chasing!)\n"
    "   - Use logical support/resistance, demand/supply zones\n"
    "   - Entry at confirmation: breakout, pullback completion, or reversal signal\n"
    "\n"
    "3. Stop-Loss (SL) - realistic and protective:\n"
    "   - Major coins (BTC/ETH): 1-2.5% from entry\n"
    "   - Altcoins: 2-4% from entry\n"
    "   - Place BEYOND key support (LONG) or resistance (SHORT), not at round numbers\n"
    "\n"
    "4. Take-Profit targets (realistic, achievable):\n"
    "   - tp1: Conservative (≥70% probability) - for 40-50% position exit\n"
    "   - tp2: Moderate (≥55% probability) - for 30-40% exit\n"
    "   - tp3: Aggressive (≥40% probability) - for remaining 10-20%\n"
    "   - All TPs must be profitable and align with recent price action\n"
    "\n"
    "5. Trend respect:\n"
    "   - NEVER trade against strong trends (danger_chop=true → avoid)\n"
    "   - Align with momentum: uptrend → LONG bias, downtrend → SHORT bias\n"
    "\n"
    "6. Success probability (realistic):\n"
    "   - Report 50-70% for solid setups (not 80-90%!)\n"
    "   - Consider: trend strength, volume, support/resistance quality\n"
    "\n"
    "EXAMPLES OF GOOD TRADES:\n"
    "- BTCUSDT at 68500: LONG entry=68350, sl=67600 (1.1% risk), tp1=69800 (2.1% reward) → RR=1.91\n"
    "- ETHUSDT at 2450: SHORT entry=2455, sl=2505 (2.0% risk), tp1=2360 (3.9% reward) → RR=1.95\n"
    "- SOLUSDT at 145: LONG entry=144.8, sl=142 (1.9% risk), tp1=148.5 (2.6% reward) → RR=1.37\n"
    "\n"
    "If market is choppy or no clear setup exists, return minimal/null values.\n"
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
    if not ALERT_INGEST_URL:
        LOGGER.error("ALERT_INGEST_URL not set")
        return False
    try:
        body, headers = build_signed_outbound(
            WEBHOOK_HMAC_SECRET, payload,
            idempotency_key=generate_idempotency_key(),
            extra_headers={"Content-Type":"application/json"},
        )
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(ALERT_INGEST_URL, content=body, headers=headers)
            r.raise_for_status()
            return True
    except Exception as e:
        LOGGER.warning("emit failed: %s", e)
        return False

# ---------------- Proposers ----------------
def _min_rr_for(symbol: str, ctx_filters: Dict[str, Any]) -> float:
    # אם קיים min_rr מה-Context – נשתמש בו; אחרת Top10/Alt
    if ctx_filters and isinstance(ctx_filters.get("min_rr"), (int, float)):
        return float(ctx_filters["min_rr"])
    return MIN_RR_TOP10 if is_top10(symbol) else MIN_RR_ALT

async def _apply_funding_bias_req(side: str, symbol: str, min_rr: float, success_min: float) -> Tuple[float, float, str]:
    fb = float(await funding_bias_for_symbol(symbol))
    reason = ""
    # fb>0 → תומך LONG; fb<0 → תומך SHORT
    opposed = (side=="LONG" and fb < 0) or (side=="SHORT" and fb > 0)
    aligned = (side=="LONG" and fb > 0) or (side=="SHORT" and fb < 0)
    
    # ביטול funding bias - מחזיר ערכים מקוריים!
    if opposed:
        reason = f"funding_opposed({fb:+.2f})"
    elif aligned:
        reason = f"funding_aligned({fb:+.2f})"
    
    return (min_rr, success_min, reason)  # אין שינוי בסף!

async def _gpt_suggest(symbol: str, ctx: Dict[str, Any], for_spot: bool) -> Optional[Dict[str, Any]]:
    if not OPENAI_API_KEY:
        LOGGER.error("OPENAI_API_KEY missing")
        return None
    
    # 🧠 SELF-ADAPTIVE ENGINE: Analyze market conditions
    # Ensure symbol is in ctx for database persistence
    if ctx is None:
        ctx = {}
    ctx["symbol"] = symbol
    
    mi_engine = get_market_intelligence()
    
    # 📊 Enhanced Multi-TF Analysis with Weighted Priority (4H=50%, 1H=30%, 15M=20%)
    if "multi_tf" in ctx and ctx["multi_tf"]:
        # Build multi-TF contexts for market intelligence
        multi_tf_contexts = {}
        for interval, tf_data in ctx["multi_tf"].items():
            # Extract indicators from each timeframe
            # NOTE: Data is in 'indicators' not 'filters'!
            indicators = tf_data.get("indicators", {})
            filters = tf_data.get("filters", {})
            
            multi_tf_contexts[interval] = {
                "symbol": symbol,
                "close": tf_data.get("price"),
                # Indicators are the numeric values
                "adx": indicators.get("adx"),
                "atr_percent": indicators.get("atr_pct"),
                "rsi": indicators.get("rsi"),
                "ema_20": indicators.get("ema21"),
                "ema_50": indicators.get("ema50"),
                # Filters contain derived flags
                "macd": filters.get("macd", 0.0),
                "bb_width_pct": filters.get("bb_width", 5.0),
            }
            
            # 💾 Save TF snapshot to database for historical analysis
            try:
                insert_tf_snapshot({
                    "symbol": symbol,
                    "interval": interval,
                    "timestamp": time.time(),
                    "indicators": indicators,
                    "alignment_status": "PENDING"  # Will be updated below
                })
            except Exception as e:
                LOGGER.debug(f"Failed to save TF snapshot: {e}")
        
        # 🎯 Weighted Multi-TF Analysis (Sniper-Grade)
        # 4H = 50% (Trend Direction), 1H = 30% (Confirmation), 15M = 20% (Entry Timing)
        weighted_analysis = analyze_multi_tf_weighted(multi_tf_contexts)
        
        # Log weighted analysis with all details
        LOGGER.info(
            f"🎯 Weighted Multi-TF [{symbol}]: "
            f"Dominant={weighted_analysis.dominant_timeframe.upper()}, "
            f"Trend={weighted_analysis.trend_direction}, "
            f"Confidence={weighted_analysis.weighted_confidence:.1f}%, "
            f"Alignment={weighted_analysis.alignment_status}, "
            f"TF Scores: 4H={weighted_analysis.tf_scores.get('4h', 0):.0f}% (50% weight), "
            f"1H={weighted_analysis.tf_scores.get('1h', 0):.0f}% (30%), "
            f"15M={weighted_analysis.tf_scores.get('15m', 0):.0f}% (20%)"
        )
        
        # Update TF snapshots with alignment status
        try:
            for interval in multi_tf_contexts.keys():
                insert_tf_snapshot({
                    "symbol": symbol,
                    "interval": interval,
                    "timestamp": time.time(),
                    "indicators": multi_tf_contexts[interval],
                    "alignment_status": weighted_analysis.alignment_status
                })
        except Exception as e:
            LOGGER.debug(f"Failed to update TF alignment: {e}")
        
        # Use market intelligence for final decision
        market_condition = mi_engine.analyze_multi_tf(multi_tf_contexts)
        LOGGER.info(
            f"Market Intel [{symbol}]: "
            f"TF-Alignment={market_condition.tf_alignment}, "
            f"Strategy={market_condition.recommended_strategy}"
        )
    else:
        # Fallback to single-TF analysis
        market_condition = mi_engine.analyze_market(ctx)
    
    # Store market_condition in ctx for later use (Dynamic Sizing, Flip Intelligence)
    ctx["_market_condition"] = market_condition
    
    # 📝 Generate adaptive prompt based on market regime
    prompt_engine = get_adaptive_prompt_engine()
    
    # For SPOT, use conservative prompt; for FUTURES, use regime-specific prompt
    if for_spot:
        sys_prompt = PROMPT_SYS_SPOT  # SPOT keeps original prompt
    else:
        # 🎯 Adaptive Futures prompt based on market conditions
        sys_prompt = prompt_engine.generate_prompt(market_condition, symbol, ctx or {})
    
    cli = _get_client()
    user = _build_user_ctx(symbol, ctx or {})
    
    try:
        resp = cli.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role":"system","content":sys_prompt},{"role":"user","content":user}],
            max_completion_tokens=300,
            response_format={"type":"json_object"},
        )
        content = resp.choices[0].message.content or ""
        data = _parse_json_safe(content) or {}
        side = str(data.get("side","")).upper()
        if for_spot and side != "LONG":  # SPOT always LONG
            side = "LONG"
        lev = _to_int(data.get("leverage"), default=10) or 10
        lev = max(SUGGEST_MIN_LEVERAGE, min(SUGGEST_MAX_LEVERAGE, lev))
        prop = {
            "symbol": symbol,
            "side": side if side in ("LONG","SHORT") else None,
            "entry": _to_float(data.get("entry")),
            "sl": _to_float(data.get("sl")),
            "tp1": _to_float(data.get("tp1")),
            "tp2": _to_float(data.get("tp2")),
            "tp3": _to_float(data.get("tp3")),
            "leverage": (1 if for_spot else lev),
            "success_pct": _to_float(data.get("success_pct")),
            "reason": data.get("reason") or "",
        }
        if prop["side"] not in ("LONG","SHORT"):
            return None
        if prop["entry"] is None or prop["sl"] is None or prop["tp1"] is None:
            return None
        
        # ✨ ADAPTIVE AI Response Validation - Dynamic RR threshold!
        # Use market-intelligent minimum RR (adapts to conditions)
        rr_check = rr_from_levels(prop["entry"], prop["sl"], prop["tp1"])
        MIN_AI_RR = market_condition.min_rr_threshold  # 🎯 DYNAMIC threshold
        
        if rr_check is not None and rr_check < MIN_AI_RR:
            LOGGER.info(
                f"AI_REJECTED {symbol}: RR={rr_check:.3f} < {MIN_AI_RR:.2f} "
                f"(regime={market_condition.regime}, mood={market_condition.mood})"
            )
            return None
        
        # בדיקת success_pct סביר (לא 0 או 100)
        if prop.get("success_pct") is not None:
            if prop["success_pct"] < 35 or prop["success_pct"] > 95:
                LOGGER.info(f"AI_REJECTED {symbol}: unrealistic success_pct={prop['success_pct']} (should be 35-95%)")
                return None
        
        # ✅ Log market intelligence for debugging
        LOGGER.debug(
            f"Market Intel for {symbol}: {market_condition.regime}/{market_condition.mood}, "
            f"strategy={market_condition.recommended_strategy}, min_rr={MIN_AI_RR:.2f}"
        )
        
        return prop
    except Exception as e:
        LOGGER.warning("gpt error %s", e)
        return None

def _calc_dynamic_budget(symbol: str, ctx: Dict[str, Any]) -> float:
    """
    משתמש ב־get_trade_budget_usdt; אם דינמי כבוי נחזור לערך ENV.
    נעשה ניסיון להעביר quality/ATR/price מה־context אם קיימים.
    """
    price = _maybe_float(ctx, "price") or _maybe_float(ctx.get("filters", {}), "price") or None
    atr   = _maybe_float(ctx, "atr", "atr14", "atr_abs") or _maybe_float(ctx.get("filters", {}), "atr", "atr14") or None
    quality = _quality_from_ctx(ctx)
    try:
        b = float(get_trade_budget_usdt(symbol=symbol, quality=quality, atr=atr, price=price))
        if b > 0:
            return b
    except Exception as e:
        LOGGER.debug("dynamic budget failed, fallback to ENV: %s", e)
    return float(BUDGET_USD_FALLBK)

async def propose_futures(symbol: str, ctx: Dict[str, Any], success_floor: float) -> Optional[Dict[str, Any]]:
    prop = await _gpt_suggest(symbol, ctx, for_spot=False)
    if not prop:
        LOGGER.info(f"NO PROPOSAL from AI for {symbol}")
        return None

    price = (ctx or {}).get("price")
    if not entry_gap_ok(price, prop["entry"]):  # לא לרדוף
        LOGGER.info(f"REJECTED {symbol}: entry_gap_ok failed (price={price}, entry={prop['entry']})")
        return None

    # ✨ סינונים דינמיים לפי תנאי השוק
    dynamic_filters = get_dynamic_thresholds(symbol, ctx)
    min_rr = dynamic_filters["rr_top10_min"] if is_top10(symbol) else dynamic_filters["rr_alt_min"]
    success_req = dynamic_filters["success_pct_min"]
    
    # דרישת RR + funding bias
    rr = rr_from_levels(prop["entry"], prop["sl"], prop["tp1"])
    min_rr, success_req, fb_note = await _apply_funding_bias_req(prop["side"], symbol, min_rr, success_req)
    if rr is None or rr < min_rr:
        LOGGER.info(f"REJECTED {symbol}: rr={rr} < {min_rr}")
        return None

    # גייטינג כללי
    vol_reg = ((ctx.get("filters") or {}).get("vol_regime","mid")) if ctx else "mid"
    
    # Ensure success_pct is a valid number (fallback to success_req if None/missing)
    success_pct = prop.get("success_pct")
    if success_pct is None or not isinstance(success_pct, (int, float)):
        success_pct = success_req or SUCCESS_PCT_MIN
        LOGGER.debug(f"{symbol}: GPT didn't provide success_pct, using fallback={success_pct}")
    
    # Debug: Log all parameters before calling gate_trade
    LOGGER.debug(
        f"🔍 {symbol} gate_trade params: side={prop['side']}, price={price}, "
        f"entry={prop['entry']}, sl={prop['sl']}, tp1={prop['tp1']}, "
        f"vol_regime={vol_reg}, success_pct={success_pct}, leverage={prop.get('leverage')}"
    )
    
    g = gate_trade(symbol, prop["side"], price, prop["entry"], prop["sl"], prop["tp1"],
                   vol_regime=vol_reg, success_pct=success_pct, leverage=prop.get("leverage"))
    if not g["ok"]:
        reason = ", ".join(g.get("errors", ["unknown"]))
        LOGGER.info(f"REJECTED {symbol}: gate_trade failed - {reason}")
        return None

    if success_pct < success_req:  # סף הצלחה דינמי
        LOGGER.info(f"REJECTED {symbol}: success_pct={success_pct} < {success_req}")
        return None

    # 🚀 DYNAMIC LEVERAGE & POSITION SIZING
    # Calculate optimal leverage and position size based on trade quality
    try:
        from utils.binance_client import _init_client
        cli = _init_client()
        if cli:
            acc_info = cli.futures_account()
            account_equity = float(acc_info.get("totalWalletBalance", 10000.0)) if acc_info else 10000.0
        else:
            account_equity = 10000.0
    except Exception:
        account_equity = 10000.0  # Safe fallback
    
    quality_score = _quality_from_ctx(ctx) or 5.0  # Default medium quality
    volatility = (ctx.get("filters") or {}).get("vol_regime", "medium") or "medium"
    market_condition = ctx.get("_market_condition")  # Stored earlier by _gpt_suggest
    
    dynamic_sizing_engine = get_dynamic_sizing_engine()
    sizing = dynamic_sizing_engine.calculate_position(
        quality_score=quality_score,
        risk_reward=rr,
        ai_confidence=prop.get("success_pct") or 70.0,
        volatility=volatility,
        account_equity=account_equity,
        market_regime=market_condition.regime if market_condition else "unknown",
        market_mood=market_condition.mood if market_condition else "neutral"
    )
    
    # Use dynamic sizing instead of GPT's leverage
    leverage = sizing.leverage
    budget = sizing.size_usd / leverage  # Budget from dynamic sizing
    notional = sizing.size_usd
    
    LOGGER.info(
        f"💰 Dynamic Sizing: {symbol} {prop['side']} → "
        f"Leverage={leverage}x, Budget=${budget:.2f}, Position=${notional:.2f}"
    )

    # נזילות (סליפג')
    lg = liquidity_gate_safe(symbol, prop["side"], notional_usd=notional)
    if asyncio.iscoroutine(lg):
        lg = await lg
    if not (lg.get("ok") if isinstance(lg, dict) else lg):
        return None

    # 📊 AI PERFORMANCE TRACKING: Log prediction for Win% calculation
    try:
        # Extract market regime from market_condition
        regime_str = market_condition.regime.upper() if market_condition and hasattr(market_condition, 'regime') else "UNKNOWN"
        if regime_str not in ("TRENDING", "RANGING", "VOLATILE", "UNKNOWN"):
            regime_str = "UNKNOWN"
        regime: MarketRegime = regime_str  # type: ignore
        
        # Extract features from context for tracking
        features = {
            "rr": rr,
            "quality_score": quality_score,
            "volatility": volatility,
            "atr": _maybe_float(ctx, "atr", "atr14", "atr_abs"),
            "rsi": _maybe_float((ctx.get("filters") or {}), "rsi"),
            "adx": _maybe_float((ctx.get("filters") or {}), "adx"),
            "volume_regime": vol_reg,
            "price": price,
            "leverage": leverage,
        }
        
        # Log prediction with ai_tracker
        prediction_id = log_prediction(
            symbol=symbol,
            ai_model="gpt5",  # Currently using GPT-5
            confidence=float(prop.get("success_pct") or 70.0) / 100.0,  # Convert % to 0-1
            prediction=prop,
            regime=regime,
            features=features
        )
    except Exception as e:
        LOGGER.warning(f"Failed to log AI prediction for {symbol}: {e}")
        prediction_id = ""

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
        "leverage": leverage,
        "budget_usd": float(budget),
        "notional_usd": float(notional),
        "qty": None,
        "chat_id": TELEGRAM_CHAT_ID or None,
        "prediction_id": prediction_id,  # Store for outcome linking
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
    min_rr, success_req, fb_note = await _apply_funding_bias_req("LONG", symbol, min_rr, success_floor)

    if rr is None or rr < min_rr:
        return None
    if (prop.get("success_pct") or 0) < success_req:
        LOGGER.info(f"REJECTED SPOT {symbol}: success_pct={prop.get('success_pct')} < {success_req}")
        return None

    budget = _calc_dynamic_budget(symbol, ctx)
    # נזילות לנוטיונל = budget בלבד
    lg = liquidity_gate_safe(symbol, "LONG", notional_usd=budget)
    if asyncio.iscoroutine(lg):
        lg = await lg
    if not (lg.get("ok") if isinstance(lg, dict) else lg):
        return None

    # 📊 AI PERFORMANCE TRACKING: Log prediction for Win% calculation
    try:
        # Extract market regime from context (SPOT uses simpler context)
        market_condition = ctx.get("_market_condition")
        regime_str = market_condition.regime.upper() if market_condition and hasattr(market_condition, 'regime') else "UNKNOWN"
        if regime_str not in ("TRENDING", "RANGING", "VOLATILE", "UNKNOWN"):
            regime_str = "UNKNOWN"
        regime: MarketRegime = regime_str  # type: ignore
        
        # Extract features from context for tracking
        features = {
            "rr": rr,
            "atr": _maybe_float(ctx, "atr", "atr14", "atr_abs"),
            "rsi": _maybe_float((ctx.get("filters") or {}), "rsi"),
            "adx": _maybe_float((ctx.get("filters") or {}), "adx"),
            "price": price,
            "leverage": 1,
        }
        
        # Log prediction with ai_tracker
        prediction_id = log_prediction(
            symbol=symbol,
            ai_model="gpt5",  # Currently using GPT-5
            confidence=float(prop.get("success_pct") or 70.0) / 100.0,  # Convert % to 0-1
            prediction=prop,
            regime=regime,
            features=features
        )
    except Exception as e:
        LOGGER.warning(f"Failed to log AI prediction for SPOT {symbol}: {e}")
        prediction_id = ""

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
        "budget_usd": float(budget),
        "notional_usd": float(budget),
        "qty": None,
        "chat_id": TELEGRAM_CHAT_ID or None,
        "prediction_id": prediction_id,  # Store for outcome linking
    }
    return payload

async def propose_grid(symbol: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if build_grid_plan is None:
        LOGGER.info(f"propose_grid SKIPPED {symbol}: build_grid_plan not available")
        return None
    price = ctx.get("price") if ctx else None
    flags = (ctx.get("filters") or {}) if ctx else {}
    plan = build_grid_plan(symbol=symbol, price=price, flags=flags, budget_usd=_calc_dynamic_budget(symbol, ctx))
    if not plan:
        LOGGER.info(f"propose_grid REJECTED {symbol}: build_grid_plan returned None (no range)")
        return None

    # נזילות לנוטיונל ≈ budget (גריד לא ממונף כאן)
    budget = float(plan.get("budget_usd") or _calc_dynamic_budget(symbol, ctx))
    lg = liquidity_gate_safe(symbol, plan["grid_side"], notional_usd=budget)
    if not (lg.get("ok") if isinstance(lg, dict) else lg):
        LOGGER.info(f"propose_grid REJECTED {symbol}: liquidity_gate failed (budget={budget})")
        return None
    
    LOGGER.info(f"✅ GRID PROPOSAL {symbol}: range {plan['grid_min']:.2f}-{plan['grid_max']:.2f}, levels={plan['grid_levels']}")

    import json
    payload = {
        "trade_id": f"g{int(time.time())}{random.randint(100,999)}",
        "trade_type": "GRID",
        "symbol": symbol,
        "side": plan["grid_side"],  # תואם ל-/alerts/ingest
        "market": "futures",
        "current_price": float(price or 0.0),
        "is_grid": True,
        "grid_min": float(plan["grid_min"]),
        "grid_max": float(plan["grid_max"]),
        "grid_levels": int(plan["grid_levels"]),
        "grid_step_pct": float(plan["grid_step_pct"]),
        "grid_take_profit_pct": float(plan["grid_take_profit_pct"]),
        "grid_side": plan["grid_side"],
        "reason": plan["reason"],
        "budget_usd": float(budget),
        "notional_usd": float(budget),
        "chat_id": TELEGRAM_CHAT_ID or None,
    }
    LOGGER.info(f"GRID PAYLOAD for {symbol}: {json.dumps(payload, default=str)}")
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
    
    # 🎯 Log dynamic filters for first symbol (for debugging)
    if pool_syms:
        sample_ctx = {"symbol": pool_syms[0], "filters": {}}
        sample_filters = get_dynamic_thresholds(pool_syms[0], sample_ctx)
        LOGGER.info(f"Dynamic Filters: {explain_filters(sample_filters)}")

    # שמור על POOL_PER_CYCLE אם ביקשת ספציפית
    random.shuffle(pool_syms)
    symbols = pool_syms[:max(1, min(POOL_PER_CYCLE, len(pool_syms)))]

    # Context batch with multi-timeframe support
    # Enable multi-TF for better analysis
    use_multi_tf = os.getenv("USE_MULTI_TF", "1").lower() in ("1", "true", "yes")
    multi_tf_intervals = ["15m", "1h", "4h"] if use_multi_tf else None
    
    ctx_map = await _fetch_context_batch(
        symbols, 
        interval=DEFAULT_INTERVAL,
        intervals=multi_tf_intervals,
        use_multi_tf=use_multi_tf
    )

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    accepted = 0
    accepted_lock = asyncio.Lock()

    # קאפ דינמי — המינימום בין env לבין topk/3 כדי לא להציף
    cap_per_cycle = max(1, min(CAP_PER_CYCLE_ENV, max(1, topk // 3)))

    async def maybe_emit(ttype: str, payload: Optional[Dict[str, Any]]):
        nonlocal accepted
        if not payload:
            return
        
        # 🛡️ PORTFOLIO INTELLIGENCE: Check exposure limits before emitting
        portfolio_intel = get_portfolio_intelligence()
        symbol = payload.get("symbol", "")
        side = payload.get("side", "")
        size_usd = payload.get("budget_usd", 100.0)  # Get budget from payload
        
        can_open, rejection_reason = portfolio_intel.can_open_trade(
            symbol=symbol,
            side=side,
            size_usd=size_usd,
            reason=f"{ttype} proposal"
        )
        
        if not can_open:
            LOGGER.info(
                f"🛡️ Portfolio blocked {symbol} {side}: {rejection_reason}"
            )
            return
        
        # שמירת "טוקן" נסיונות כדי להגביל כמות שליחות בפועל
        async with accepted_lock:
            if accepted >= cap_per_cycle:
                return
            # שומרים מקום; אם תיכשל השליחה נחזיר
            accepted += 1
            reserved = True
        ok = False
        try:
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
        finally:
            if not ok:
                # החזרה של הטוקן אם נכשלנו בכל זאת
                async with accepted_lock:
                    accepted = max(0, accepted - 1)

    async def handle_symbol(sym: str):
        ctx = ctx_map.get(sym) or {}
        success_floor = SUCCESS_PCT_MIN

        # FUTURES
        if SUGGEST_FUTURES:
            try:
                p = await propose_futures(sym, ctx, success_floor)
                await maybe_emit("FUTURES", p)
            except Exception as e:
                LOGGER.exception(f"propose_futures error {sym}: {e}")

        # SPOT
        if SUGGEST_SPOT:
            try:
                p = await propose_spot(sym, ctx, success_floor)
                await maybe_emit("SPOT", p)
            except Exception as e:
                LOGGER.debug("propose_spot error %s: %s", sym, e)

        # GRID
        if SUGGEST_GRID:
            try:
                p = await propose_grid(sym, ctx)
                await maybe_emit("GRID", p)
            except Exception as e:
                LOGGER.info(f"propose_grid ERROR {sym}: {e}")

    async def worker(sym: str):
        async with sem:
            await handle_symbol(sym)

    await asyncio.gather(*(worker(s) for s in symbols), return_exceptions=True)
    LOGGER.info("cycle finished: symbols=%d accepted=%d cap=%d", len(symbols), accepted, cap_per_cycle)

async def main():
    # Log feature toggles at startup
    LOGGER.info(f"🚀 Auto-suggest started: FUTURES={SUGGEST_FUTURES}, SPOT={SUGGEST_SPOT}, GRID={SUGGEST_GRID}")
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
















