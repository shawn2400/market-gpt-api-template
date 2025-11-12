# workers/gpt_auto_suggest.py
from __future__ import annotations
import os, json, time, asyncio, hashlib, logging, random
from typing import Dict, Any, List, Optional, Tuple

import httpx
# OpenAI import removed - using DeepSeek + Gemini for cost optimization

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
from utils.ai_trade_scorer import get_multi_ai_scorer  # ← Multi-AI Consensus (5 providers)
from utils.strategy_orchestrator import get_strategy_orchestrator  # ← Strategy Orchestrator (Auto-select strategy)
from utils.metabrain.dynamic_protection_manager import protection_manager  # ← Dynamic Protection Manager (Regime-based params)

# Grid helper
try:
    from utils.grid_builder import build_grid_plan
except Exception:
    build_grid_plan = None

# Mean-Reversion helper
try:
    from utils.mean_reversion_strategy import calculate_mean_reversion_levels
except Exception:
    calculate_mean_reversion_levels = None

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

async def _fetch_real_indicators(symbol: str, interval: str = "15m", limit: int = 200) -> Dict[str, Any]:
    """
    🎯 LIVE BINANCE DATA - Fetch real klines and calculate all indicators
    """
    try:
        from utils.get_klines import get_klines
        from utils.symbols import normalize_symbol
        from utils.indicators import rsi, adx, atr, macd, bollinger_bands, ema
        
        # Fetch real klines from Binance (v3.0.0 - no caching, always fresh data)
        df = await get_klines(symbol, interval=interval, limit=limit, market_type="futures")
        
        if df.empty or len(df) < 50:
            LOGGER.warning(f"⚠️ {symbol}: Insufficient klines data ({len(df)} candles)")
            return {}
        
        close = df["close"]
        price = float(close.iloc[-1])
        
        # Calculate all indicators from REAL data
        rsi_val = rsi(close, period=14)
        adx_val = adx(df, period=14)
        atr_val = atr(df, period=14)
        macd_line, macd_signal, macd_hist = macd(close, fast=12, slow=26, signal=9)
        bb_mid, bb_upper, bb_lower = bollinger_bands(close, period=20, std_factor=2.0)
        ema20 = ema(close, period=20)
        ema50 = ema(close, period=50)
        
        # Calculate volume averages
        volume_sma_20 = df["volume"].rolling(window=20, min_periods=1).mean()
        
        # ATR as percentage of price
        atr_pct = (float(atr_val.iloc[-1]) / price * 100.0) if not atr_val.empty else 2.0
        
        # 🎯 Calculate 24H high/low for AI Strategy Consensus
        candles_24h = 96 if interval == "15m" else (24 if interval == "1h" else 6)
        recent_klines = df.tail(min(len(df), candles_24h))
        high_24h = float(recent_klines["high"].max()) if len(recent_klines) > 0 else price
        low_24h = float(recent_klines["low"].min()) if len(recent_klines) > 0 else price
        
        indicators = {
            "price": price,
            "close": price,
            "high_24h": high_24h,
            "low_24h": low_24h,
            "rsi": round(float(rsi_val.iloc[-1]), 2) if not rsi_val.empty else 50.0,
            "adx": round(float(adx_val.iloc[-1]), 2) if not adx_val.empty else 25.0,
            "atr": round(float(atr_val.iloc[-1]), 6),
            "atr_percent": round(atr_pct, 2),
            "macd": round(float(macd_line.iloc[-1]), 6) if not macd_line.empty else 0.0,
            "macd_signal": round(float(macd_signal.iloc[-1]), 6) if not macd_signal.empty else 0.0,
            "macd_hist": round(float(macd_hist.iloc[-1]), 6) if not macd_hist.empty else 0.0,
            "bb_upper": round(float(bb_upper.iloc[-1]), 6) if not bb_upper.empty else price * 1.02,
            "bb_mid": round(float(bb_mid.iloc[-1]), 6) if not bb_mid.empty else price,
            "bb_lower": round(float(bb_lower.iloc[-1]), 6) if not bb_lower.empty else price * 0.98,
            "ema_20": round(float(ema20.iloc[-1]), 6) if not ema20.empty else price,
            "ema_50": round(float(ema50.iloc[-1]), 6) if not ema50.empty else price,
            "volume": float(df["volume"].iloc[-1]),
            "volume_sma_20": round(float(volume_sma_20.iloc[-1]), 2) if not volume_sma_20.empty else 1000000
        }
        
        LOGGER.info(
            f"📊 LIVE Indicators [{symbol}]: "
            f"RSI={indicators['rsi']:.1f}, ADX={indicators['adx']:.1f}, "
            f"ATR={indicators['atr_percent']:.2f}%, MACD={indicators['macd']:.4f}"
        )
        
        return indicators
        
    except Exception as e:
        LOGGER.error(f"❌ Failed to fetch real indicators for {symbol}: {e}")
        return {}

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

# REMOVED: OpenAI config (cost optimization)
# OPENAI_API_KEY and OPENAI_MODEL no longer used
# System now uses DeepSeek (primary) + Gemini (fallback) for 95% cost reduction

CONTEXT_URL = os.getenv("CONTEXT_URL","").strip()  # למשל: https://your-host
ALERT_INGEST_URL = os.getenv("ALERT_INGEST_URL","http://127.0.0.1:8000/alerts/trade-ingest").strip()
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET","").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", os.getenv("ADMIN_CHAT_ID","")).strip()

SUGGEST_ENABLED   = os.getenv("TRADE_AUTO_SUGGEST","1").lower() in ("1","true","yes")
POOL_PER_CYCLE    = int(os.getenv("SYMBOLS_PER_CYCLE","50"))  # 🚀 Increased from 10 to 50 for better market coverage
MAX_CONCURRENCY   = int(os.getenv("OPENAI_MAX_CONCURRENCY","2"))
CAP_PER_CYCLE_ENV = int(os.getenv("SUGGEST_CAP_PER_CYCLE","5"))

SUCCESS_PCT_MIN   = float(os.getenv("SUCCESS_PCT_MIN","70"))

# תקציב בסיס (ישמש כפולבק אם הדינמי כבוי)
BUDGET_USD_FALLBK = float(os.getenv("MAX_TRADE_BUDGET","100"))

# סוגי הצעות להפעלה
SUGGEST_FUTURES   = os.getenv("SUGGEST_FUTURES","1").strip().lower() in ("1","true","yes")
SUGGEST_SPOT      = os.getenv("SUGGEST_SPOT","0").strip().lower() in ("1","true","yes")
SUGGEST_GRID      = os.getenv("SUGGEST_GRID","1").strip().lower() in ("1","true","yes")  # ✅ Enabled GRID by default

DEFAULT_INTERVAL  = os.getenv("DEFAULT_INTERVAL","15m")

MIN_RR_TOP10 = float(os.getenv("MIN_RR_TOP10", "1.10"))  # 🎯 Lowered for more trades (Top10 symbols)
MIN_RR_ALT   = float(os.getenv("MIN_RR_ALT", "1.15"))  # 🎯 Lowered for more trades (Altcoins)

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
        LOGGER.warning("CONTEXT_URL not set – using local context fallback")
        return await _build_local_context(symbols, interval)
    
    # 🎯 CRITICAL: Use compact=False to get indicators (high_24h, low_24h, volume) for AI Strategy Consensus
    payload = {"symbols": symbols, "interval": interval, "compact": False}
    
    # Add multi-TF support if enabled
    if use_multi_tf and intervals:
        payload["intervals"] = intervals
    
    # Get API key for authentication (prefer Bearer token for internal calls)
    bearer_token = os.getenv("API_BEARER_TOKEN") or ""
    primary_token = os.getenv("PRIMARY_API_TOKEN") or os.getenv("API_TOKEN") or ""
    
    headers = {}
    if bearer_token:
        # Use Authorization: Bearer for internal worker → main app calls
        headers["Authorization"] = f"Bearer {bearer_token}"
    elif primary_token:
        # Fallback to X-API-Key if PRIMARY_API_TOKEN is set
        headers["X-API-Key"] = primary_token
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(CONTEXT_URL.rstrip("/") + "/context/batch", json=payload, headers=headers)
            r.raise_for_status()
            resp_data = r.json()
            
            out = {}
            
            # Single-TF mode (backward compatible)
            if not use_multi_tf or "multi_tf_items" not in resp_data:
                for it in resp_data.get("items", []):
                    symbol = it["symbol"]
                    ctx = {"symbol": symbol, "price": it.get("price")}
                    ctx.update(it.get("indicators", {}))
                    ctx.update(it.get("filters", {}))
                    ctx["close"] = it.get("price")
                    out[symbol] = ctx
                return out
            
            # Multi-TF mode - combine multi_tf data with primary context
            for it in resp_data.get("items", []):
                symbol = it["symbol"]
                ctx = {"symbol": symbol, "price": it.get("price")}
                ctx.update(it.get("indicators", {}))
                ctx.update(it.get("filters", {}))
                ctx["close"] = it.get("price")
                out[symbol] = ctx
            
            # Add multi_tf data to each symbol's context
            for mt_item in resp_data.get("multi_tf_items", []):
                symbol = mt_item["symbol"]
                if symbol in out:
                    out[symbol]["multi_tf"] = mt_item.get("multi_tf", {})
            
            return out
    except Exception as e:
        LOGGER.warning("context batch failed: %s", e)
        # 🔄 FALLBACK: Build context locally from Binance if API fails
        LOGGER.info("🔄 Building context locally for %d symbols (API fallback)", len(symbols))
        return await _build_local_context(symbols, interval)

async def _build_local_context(symbols: List[str], interval: str = "15m") -> Dict[str, Dict[str, Any]]:
    """
    Minimal context fallback when Context API is unavailable.
    
    Returns minimal context with symbol keys so downstream pipeline processes each symbol.
    Actual indicator calculation happens in _fetch_real_indicators later in the pipeline.
    """
    LOGGER.info(
        f"Context API unavailable - building minimal context for {len(symbols)} symbols. "
        f"Full indicators will be calculated via _fetch_real_indicators."
    )
    
    # Return minimal context dict with symbol keys so downstream logic processes them
    return {symbol: {"symbol": symbol, "interval": interval} for symbol in symbols}

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

def _get_regime_quality_threshold(ctx: Dict[str, Any]) -> float:
    """
    Get quality threshold based on market regime from Dynamic Protection Manager.
    Returns regime-specific entry_quality_min (5.8-6.5 depending on regime).
    """
    try:
        # Extract regime from context
        regime = (ctx.get("filters") or {}).get("regime", "").upper()
        
        # Map regime names to protection manager format
        regime_map = {
            "TREND": "TRENDING",
            "TRENDING": "TRENDING",
            "CHOP": "CHOPPY",
            "CHOPPY": "CHOPPY",
            "VOLATILE": "VOLATILE",
            "BREAKOUT": "TRENDING",  # Breakout behaves like trending
            "MEAN_REVERT": "SIDEWAYS",  # Mean reversion behaves like sideways
            "SIDEWAYS": "SIDEWAYS"
        }
        
        regime_key = regime_map.get(regime, "CHOPPY")  # Default to CHOPPY (most conservative)
        protection = protection_manager.get_base_protection(regime_key)  # type: ignore
        
        return protection.get("entry_quality_min", 6.0)
    except Exception as e:
        LOGGER.debug(f"Failed to get regime quality threshold: {e}, using default 6.0")
        return 6.0  # Safe default

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

# ---------------- REMOVED: OpenAI Client (Cost Optimization) ----------------
# _get_client() was removed - now using DeepSeek + Gemini for 95% cost reduction
# OpenAI dependency eliminated completely

PROMPT_SYS = (
    "You are an expert crypto trading strategist focused on HIGH-QUALITY, HIGH-PROFIT trades.\n"
    "You will receive compact market context: current price and boolean/enum filters.\n"
    "Return ONLY JSON with fields:\n"
    "  side ('LONG'|'SHORT'), entry, sl, tp1, tp2, tp3, leverage (int), success_pct (0..100), reason (short).\n"
    "\n"
    "⚠️ IMPORTANT: RR (Risk/Reward) requirements are DYNAMIC based on market regime! ⚠️\n"
    "CRITICAL RULES (MUST FOLLOW):\n"
    "1. Risk/Reward (RR) calculation - **THIS IS MANDATORY**:\n"
    "   - RR = |entry - tp1| / |entry - sl|\n"
    "   - **MINIMUM RR varies by market type** (will be specified in context)\n"
    "   - CHOPPY/SIDEWAYS: RR ≥ 1.1 (tight scalps acceptable!)\n"
    "   - TRENDING: RR ≥ 1.25 (larger moves available)\n"
    "   - VOLATILE: RR ≥ 1.4 (wider stops needed)\n"
    "   \n"
    "   Examples:\n"
    "   ✓ CHOPPY: entry=100, sl=99.2 (-0.8%), tp1=101.1 (+1.1%) → RR=1.38 EXCELLENT SCALP!\n"
    "   ✓ TRENDING: entry=100, sl=98 (-2%), tp1=104 (+4%) → RR=2.0 STRONG!\n"
    "   ✗ BAD: entry=100, sl=98 (-2%), tp1=101.5 (+1.5%) → RR=0.75 REJECT\n"
    "\n"
    "2. Entry placement:\n"
    "   - MUST be within 0.3-1.5% of current price (depends on regime)\n"
    "   - Use logical support/resistance, demand/supply zones\n"
    "   - Entry at confirmation: breakout, pullback completion, or reversal signal\n"
    "\n"
    "3. Stop-Loss (SL) - realistic and protective:\n"
    "   - CHOPPY markets: 0.5-2% tight stops (precision trades!)\n"
    "   - TRENDING markets: 1.5-3% stops (allow breathing room)\n"
    "   - VOLATILE markets: 2-4% stops (wider swings)\n"
    "   - Place BEYOND key support (LONG) or resistance (SHORT), not at round numbers\n"
    "\n"
    "4. Take-Profit targets (realistic, achievable):\n"
    "   - tp1: Conservative (≥70% probability) - for 40-50% position exit\n"
    "   - tp2: Moderate (≥55% probability) - for 30-40% exit\n"
    "   - tp3: Aggressive (≥40% probability) - for remaining 10-20%\n"
    "   - All TPs must be profitable and align with recent price action\n"
    "\n"
    "5. Market Adaptation - EMBRACE ALL MARKET TYPES:\n"
    "   - CHOPPY/SIDEWAYS: Perfect for scalping! Look for range bounces, tight stops\n"
    "   - TRENDING: Ride momentum! Enter on pullbacks, follow the trend\n"
    "   - VOLATILE: Be selective! Wait for clear setups with wider protection\n"
    "   - **EVERY market regime has opportunity - adapt your strategy!**\n"
    "\n"
    "6. Success probability (realistic):\n"
    "   - Report 50-75% for solid setups (not 80-90%!)\n"
    "   - Consider: trend strength, volume, support/resistance quality\n"
    "\n"
    "EXAMPLES OF GOOD TRADES:\n"
    "- CHOPPY: BTCUSDT at 68500: LONG entry=68450, sl=68200 (0.4%), tp1=68900 (0.7%) → RR=1.75 (tight scalp!)\n"
    "- TRENDING: ETHUSDT at 2450: SHORT entry=2455, sl=2505 (2.0%), tp1=2360 (3.9%) → RR=1.95 (momentum!)\n"
    "- VOLATILE: SOLUSDT at 145: LONG entry=144.8, sl=141 (2.6%), tp1=150 (3.6%) → RR=1.38 (wider stops!)\n"
    "\n"
    "EVERY market condition has opportunities - find the BEST quality setups for that regime!\n"
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
        LOGGER.error("❌ emit failed: WEBHOOK_HMAC_SECRET not set")
        return False
    if not ALERT_INGEST_URL:
        LOGGER.error("❌ emit failed: ALERT_INGEST_URL not set")
        return False
    
    # 🧠 SAVE CONSENSUS TO REDIS for fills_watcher Telegram notifications
    symbol = payload.get("symbol")
    consensus_data = payload.get("consensus")
    if symbol and consensus_data:
        try:
            from utils.redis_client import redis_client as RED
            import json
            if RED:
                consensus_key = f"consensus:{symbol}"
                RED.setex(consensus_key, 3600, json.dumps(consensus_data))  # 1 hour TTL
                LOGGER.info(f"✅ Consensus saved to Redis: {consensus_key}")
        except Exception as e:
            LOGGER.warning(f"⚠️ Failed to save consensus to Redis: {e}")
    
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
        sym = payload.get("symbol", "UNKNOWN")
        side = payload.get("side", "")
        LOGGER.error(
            f"❌ emit failed for {sym} {side}: {type(e).__name__}: {e}\n"
            f"   URL: {ALERT_INGEST_URL}\n"
            f"   Payload keys: {list(payload.keys())}"
        )
        return False

# ---------------- Proposers ----------------
def _min_rr_for(symbol: str, ctx_filters: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> float:
    # 🎯 ADAPTIVE MinRR: Use dynamic filters instead of static values
    # Priority: 1) ctx min_rr, 2) dynamic filters, 3) static fallback
    if ctx_filters and isinstance(ctx_filters.get("min_rr"), (int, float)):
        return float(ctx_filters["min_rr"])
    
    # Get dynamic thresholds based on market conditions
    try:
        dynamic_filters = get_dynamic_thresholds(symbol, ctx)
        return dynamic_filters["rr_top10_min"] if is_top10(symbol) else dynamic_filters["rr_alt_min"]
    except Exception:
        # Fallback to static values if dynamic fails
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

async def _ai_consensus_suggest_v2(symbol: str, ctx: Dict[str, Any], for_spot: bool) -> Optional[Dict[str, Any]]:
    """
    🧠 AI CONSENSUS ENGINE v2 - Cost-optimized with 3 cheap brains
    Workflow: Market Intelligence + Strategy Orchestrator → DeepSeek/Gemini/Grok → ≥2 APPROVE = Execute
    """
    # Ensure symbol is in ctx
    if ctx is None:
        ctx = {}
    ctx["symbol"] = symbol
    
    # ========== FETCH LIVE BINANCE INDICATORS ==========
    # If indicators missing, fetch REAL data from Binance
    if not ctx.get("adx") or not ctx.get("rsi"):
        real_indicators = await _fetch_real_indicators(symbol, interval="15m", limit=200)
        if real_indicators:
            ctx.update(real_indicators)
        else:
            LOGGER.warning(f"⚠️ {symbol}: Failed to fetch live indicators, skipping")
            return None
    
    # ========== SCOUT 1: MARKET INTELLIGENCE ==========
    mi_engine = get_market_intelligence()
    
    # 📊 Enhanced Multi-TF Analysis
    if "multi_tf" in ctx and ctx["multi_tf"]:
        multi_tf_contexts = {}
        for interval, tf_data in ctx["multi_tf"].items():
            indicators = tf_data.get("indicators", {})
            filters = tf_data.get("filters", {})
            
            multi_tf_contexts[interval] = {
                "symbol": symbol,
                "close": tf_data.get("price"),
                "adx": indicators.get("adx"),
                "atr_percent": indicators.get("atr_pct"),
                "rsi": indicators.get("rsi"),
                "ema_20": indicators.get("ema21"),
                "ema_50": indicators.get("ema50"),
                "macd": filters.get("macd", 0.0),
                "bb_width_pct": filters.get("bb_width", 5.0),
            }
            
            try:
                insert_tf_snapshot({
                    "symbol": symbol,
                    "interval": interval,
                    "timestamp": time.time(),
                    "indicators": indicators,
                    "alignment_status": "PENDING"
                })
            except Exception as e:
                LOGGER.debug(f"Failed to save TF snapshot: {e}")
        
        weighted_analysis = analyze_multi_tf_weighted(multi_tf_contexts)
        LOGGER.info(
            f"🎯 Weighted Multi-TF [{symbol}]: "
            f"Dominant={weighted_analysis.dominant_timeframe.upper()}, "
            f"Trend={weighted_analysis.trend_direction}, "
            f"Confidence={weighted_analysis.weighted_confidence:.1f}%"
        )
        
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
        
        market_condition = mi_engine.analyze_multi_tf(multi_tf_contexts)
    else:
        market_condition = mi_engine.analyze_market(ctx)
    
    ctx["_market_condition"] = market_condition
    
    # ========== HYBRID ADAPTIVE SYSTEM: TIER + REGIME ANALYSIS ==========
    try:
        from utils.smart_tiered_system import get_smart_tiered_system
        from utils.ai_regime_analyzer import get_ai_regime_analyzer
        
        # Evaluate market strength and select appropriate tier
        tiered_system = get_smart_tiered_system()
        market_strength = tiered_system.evaluate_context(symbol, ctx, market_condition)
        
        # Analyze regime and detect shifts
        regime_analyzer = get_ai_regime_analyzer()
        regime_snapshot, regime_shift = regime_analyzer.analyze_with_shift_detection(symbol, ctx, market_condition)
        
        # Enrich context with tier and regime data for downstream usage
        ctx["_market_strength"] = market_strength
        ctx["_regime_snapshot"] = regime_snapshot
        ctx["_regime_shift"] = regime_shift
        ctx["_active_tier"] = market_strength.active_tier
        
        LOGGER.info(
            f"🎯 [{symbol}] Hybrid System: "
            f"Tier {market_strength.active_tier.tier_number} ({market_strength.active_tier.tier_name}) | "
            f"Strength={market_strength.strength_score:.1f}/10 | "
            f"Regime={regime_snapshot.regime.upper()} ({regime_snapshot.confidence:.1f}%)"
        )
        
        if regime_shift:
            LOGGER.info(
                f"🔄 [{symbol}] REGIME SHIFT DETECTED: "
                f"{regime_shift.from_regime.upper()} → {regime_shift.to_regime.upper()} | "
                f"Impact: {regime_shift.trading_impact}"
            )
    except Exception as e:
        LOGGER.warning(f"[{symbol}] Hybrid System unavailable: {e}")
        # Graceful fallback - continue without tier/regime enrichment
    
    # 🔍 DEBUG: Log what AI receives
    LOGGER.info(f"🔍 AI Strategy Context [{symbol}]: high_24h={ctx.get('high_24h')}, low_24h={ctx.get('low_24h')}, close={ctx.get('close')}, has_indicators={'adx' in ctx}")
    
    # ========== SCOUT 2: STRATEGY ORCHESTRATOR ==========
    orchestrator = get_strategy_orchestrator()
    strategy_config = await orchestrator.select_strategy(market_condition, symbol, ctx)
    
    # ========== BUILD SCOUT DATA ==========
    from utils.scout_data_builder import build_scout_data
    
    # ========== CALCULATE DYNAMIC SCORES ==========
    # Market Intelligence quality score (based on ADX/ATR/RSI/MACD)
    # 🎯 NOW STRATEGY-AWARE: ADX scoring adapts to strategy type!
    mi_quality_score = mi_engine.calculate_quality_score(ctx, strategy=strategy_config.strategy_type)
    
    # Strategy Orchestrator setup score (based on RSI/MACD/BB/Volume)
    so_setup_score = orchestrator.calculate_setup_score(ctx)
    
    LOGGER.info(
        f"📊 Strategy-Aware Scoring [{symbol}]: Strategy={strategy_config.strategy_type}, ADX={ctx.get('adx', 0):.1f}, "
        f"MI={mi_quality_score:.1f}/10 (STRATEGY-AWARE ✅), SO={so_setup_score:.1f}/10, AVG={(mi_quality_score + so_setup_score) / 2:.1f}/10"
    )
    
    # Create market intelligence result
    mi_result = {
        "regime": market_condition.regime,
        "quality_score": mi_quality_score,  # ← DYNAMIC score from indicators!
        "reasoning": f"Regime={market_condition.regime}, Mood={market_condition.mood}",
        "timestamp": time.time()
    }
    
    # Create strategy orchestrator result
    so_result = {
        "strategy": strategy_config.strategy_type,
        "score": so_setup_score,  # ← DYNAMIC score from technical signals!
        "min_rr": strategy_config.min_rr,
        "leverage": strategy_config.max_leverage,
        "sl_atr_mult": 1.5,  # Default, will be overridden by brains
        "tp_rr": strategy_config.min_rr,
        "reasoning": strategy_config.description,
        "signals": [],
        "timestamp": time.time()
    }
    
    scout_data = build_scout_data(symbol, mi_result, so_result, ctx)
    
    # ========== 5 AI BRAINS CONSENSUS ==========
    from utils.ai_decision_maker import AIConsensusEngine
    
    consensus_engine = AIConsensusEngine()
    
    # Get REAL wallet balance from Binance
    wallet_state = {"available_balance": 1000.0}  # Default fallback
    try:
        from utils.binance_client import futures_balance
        balances = futures_balance()
        for asset in balances:
            if asset.get("asset") == "USDT":
                wallet_state["available_balance"] = float(asset.get("availableBalance", 1000.0))
                break
    except Exception as e:
        LOGGER.warning(f"⚠️ Failed to fetch real balance, using fallback: {e}")
    
    LOGGER.info(f"🧠 Requesting consensus from 5 AI Brains for {symbol}...")
    
    consensus_result = await consensus_engine.get_consensus(
        scout_data=scout_data,
        market_data=ctx,
        wallet_state=wallet_state
    )
    
    # 🧠 STORE CONSENSUS IN CONTEXT for payload inclusion
    ctx["_consensus_result"] = consensus_result
    
    # Log consensus
    LOGGER.info(
        f"🗳️ CONSENSUS [{symbol}]: {consensus_result['approve_count']}/5 APPROVE | "
        f"Decision: {consensus_result['final_vote']} | "
        f"Avg Score: {consensus_result['final_score']:.1f}/10"
    )
    
    for vote in consensus_result["brain_votes"]:
        LOGGER.info(
            f"  {vote['brain']}: {vote['vote']} ({vote['score']:.1f}/10) - {vote['reasoning'][:60]}..."
        )
    
    # If REJECT, stop here
    if consensus_result["final_vote"] == "REJECT":
        LOGGER.info(f"❌ REJECTED by consensus: {symbol}")
        return None
    
    # ========== GENERATE TRADE PROPOSAL (DeepSeek + Gemini) ==========
    # 🚀 COST OPTIMIZATION: Use DeepSeek primary, Gemini fallback (NO OpenAI!)
    LOGGER.info(f"✅ CONSENSUS APPROVED - Generating trade proposal for {symbol}")
    
    # Generate adaptive prompt
    prompt_engine = get_adaptive_prompt_engine()
    
    if for_spot:
        sys_prompt = PROMPT_SYS_SPOT
    else:
        sys_prompt = prompt_engine.generate_prompt(market_condition, symbol, ctx or {})
    
    user_prompt = _build_user_ctx(symbol, ctx or {})
    data = None
    
    # Try DeepSeek first (primary, ultra-cheap)
    try:
        from utils.llm_client import llm_chat_completion
        response = await llm_chat_completion(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt}
            ],
            model="deepseek-chat",
            temperature=0.7,
            max_tokens=400
        )
        
        if response and "choices" in response:
            content = response["choices"][0]["message"]["content"]
            data = _parse_json_safe(content) or {}
            LOGGER.info(f"✅ DeepSeek generated proposal for {symbol}")
    except Exception as e:
        LOGGER.warning(f"DeepSeek proposal generation failed for {symbol}: {e}")
    
    # Fallback to Grok if DeepSeek failed
    if not data:
        try:
            from utils.xai_client import call_xai
            response = await call_xai(
                user_prompt,
                system=sys_prompt,
                temperature=0.7,
                max_tokens=400
            )
            
            if response:
                data = _parse_json_safe(response) or {}
                LOGGER.info(f"✅ Grok generated proposal for {symbol} (DeepSeek fallback)")
        except Exception as e:
            LOGGER.warning(f"Grok proposal generation failed for {symbol}: {e}")
    
    if not data:
        LOGGER.warning(f"NO PROPOSAL from AI for {symbol}")
        return None
    
    # Parse and validate proposal
    side = str(data.get("side","")).upper()
    if for_spot and side != "LONG":
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
    
    # Validate RR
    rr_check = rr_from_levels(prop["entry"], prop["sl"], prop["tp1"])
    MIN_AI_RR = market_condition.min_rr_threshold
    
    if rr_check is not None and rr_check < MIN_AI_RR:
        LOGGER.info(
            f"AI_REJECTED {symbol}: RR={rr_check:.3f} < {MIN_AI_RR:.2f} "
            f"(regime={market_condition.regime}, mood={market_condition.mood})"
        )
        return None
    
    # Validate success_pct
    if prop.get("success_pct") is not None:
        if prop["success_pct"] < 35 or prop["success_pct"] > 95:
            LOGGER.info(f"AI_REJECTED {symbol}: unrealistic success_pct={prop['success_pct']}")
            return None
    
    LOGGER.info(f"✅ Trade proposal generated for {symbol}: {prop['side']} @ {prop['entry']}, SL={prop['sl']}, TP={prop['tp1']}")
    return prop


async def _gpt_suggest(symbol: str, ctx: Dict[str, Any], for_spot: bool) -> Optional[Dict[str, Any]]:
    """
    COST-OPTIMIZED FUNCTION - Calls _ai_consensus_suggest_v2
    Uses 3 cheap brains: DeepSeek, Gemini, Grok
    """
    return await _ai_consensus_suggest_v2(symbol, ctx, for_spot)
    
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
    
    # 🎯 REGIME-BASED QUALITY FILTER (from Dynamic Protection Manager)
    quality_score = _quality_from_ctx(ctx)
    min_quality = _get_regime_quality_threshold(ctx)
    if quality_score is not None and quality_score < min_quality:
        regime = (ctx.get("filters") or {}).get("regime", "UNKNOWN")
        LOGGER.info(
            f"REJECTED {symbol}: quality={quality_score:.1f} < {min_quality:.1f} "
            f"(regime={regime}, threshold from Protection Manager)"
        )
        return None

    price = (ctx or {}).get("price")
    if not entry_gap_ok(price, prop["entry"]):  # לא לרדוף
        LOGGER.info(f"REJECTED {symbol}: entry_gap_ok failed (price={price}, entry={prop['entry']})")
        return None

    # 🎯 STRATEGY ORCHESTRATOR: Auto-select optimal strategy based on market conditions
    market_condition = ctx.get("_market_condition")  # Stored by _gpt_suggest
    orchestrator = get_strategy_orchestrator()
    strategy_config = await orchestrator.select_strategy(market_condition, symbol, ctx)
    
    # Use strategy-specific thresholds instead of generic dynamic filters
    min_rr = strategy_config.min_rr
    success_req = max(success_floor, strategy_config.min_success_pct)
    
    LOGGER.info(
        f"🎯 {symbol}: Strategy=[{strategy_config.strategy_type.upper()}] "
        f"MinRR={min_rr:.2f}, MinSuccess={success_req:.1f}%, MaxLev={strategy_config.max_leverage}x"
    )
    
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

    # 🧠 ADD CONSENSUS DATA for Telegram notifications
    consensus_data = ctx.get("_consensus_result") if ctx else None
    
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
        "consensus": consensus_data,  # 🧠 5 AI Brains voting data
    }
    return payload

async def propose_spot(symbol: str, ctx: Dict[str, Any], success_floor: float) -> Optional[Dict[str, Any]]:
    prop = await _gpt_suggest(symbol, ctx, for_spot=True)
    if not prop: return None
    
    # 🎯 REGIME-BASED QUALITY FILTER (from Dynamic Protection Manager)
    quality_score = _quality_from_ctx(ctx)
    min_quality = _get_regime_quality_threshold(ctx)
    if quality_score is not None and quality_score < min_quality:
        regime = (ctx.get("filters") or {}).get("regime", "UNKNOWN")
        LOGGER.info(
            f"REJECTED SPOT {symbol}: quality={quality_score:.1f} < {min_quality:.1f} "
            f"(regime={regime}, threshold from Protection Manager)"
        )
        return None
    
    price = ctx.get("price") if ctx else None
    if not entry_gap_ok(price, prop["entry"]):
        return None

    rr = rr_from_levels(prop["entry"], prop["sl"], prop["tp1"])
    min_rr = _min_rr_for(symbol, (ctx or {}).get("filters") or {}, ctx)  # 🎯 Pass ctx for dynamic filters
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

async def propose_mean_reversion(symbol: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Propose mean-reversion trade for NEUTRAL/CHOPPY markets with range <2%
    Uses VWAP + Keltner Bands for deterministic entry/exit levels
    """
    if calculate_mean_reversion_levels is None:
        LOGGER.info(f"propose_mean_reversion SKIPPED {symbol}: module not available")
        return None
    
    price = ctx.get("price") if ctx else None
    if not price:
        LOGGER.info(f"propose_mean_reversion SKIPPED {symbol}: no price")
        return None
    
    # Get OHLCV data for VWAP calculation - fetch directly from Binance
    try:
        import pandas as pd
        import httpx
        from utils.indicators import atr as calculate_atr_series
        
        # Fetch real OHLCV data from Binance for accurate VWAP calculations
        df = None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://fapi.binance.com/fapi/v1/klines",
                    params={"symbol": symbol, "interval": "15m", "limit": 180}
                )
                if resp.status_code == 200:
                    klines = resp.json()
                    if len(klines) >= 60:
                        df_data = []
                        for k in klines:
                            df_data.append({
                                "open": float(k[1]),
                                "high": float(k[2]),
                                "low": float(k[3]),
                                "close": float(k[4]),
                                "volume": float(k[5])
                            })
                        df = pd.DataFrame(df_data)
                        LOGGER.info(f"propose_mean_reversion {symbol}: Using real 15m OHLCV data ({len(df)} candles)")
                    else:
                        LOGGER.warning(f"propose_mean_reversion {symbol}: Insufficient candles from Binance ({len(klines)})")
                else:
                    LOGGER.warning(f"propose_mean_reversion {symbol}: Binance API returned {resp.status_code}")
        except Exception as e:
            LOGGER.error(f"propose_mean_reversion {symbol}: Failed to fetch OHLCV data: {e}")
        
        # CRITICAL: No synthetic fallback - if we can't get real data, skip the trade
        if df is None or len(df) < 60:
            LOGGER.info(f"propose_mean_reversion SKIPPED {symbol}: No real OHLCV data available")
            return None
        
        # Calculate ATR directly from OHLCV data
        atr_series = calculate_atr_series(df, period=14)
        if atr_series is None or len(atr_series) == 0:
            LOGGER.info(f"propose_mean_reversion SKIPPED {symbol}: ATR calculation failed")
            return None
        
        # Get the last ATR value
        atr_val = float(atr_series.iloc[-1])
        if atr_val <= 0:
            LOGGER.info(f"propose_mean_reversion SKIPPED {symbol}: ATR value too low ({atr_val})")
            return None
        
        LOGGER.info(f"propose_mean_reversion {symbol}: Calculated ATR={atr_val:.6f}")
        
        # Calculate mean-reversion levels
        levels = calculate_mean_reversion_levels(
            price=price,
            df=df,
            atr_val=float(atr_val)
        )
        
        if not levels:
            LOGGER.debug(f"propose_mean_reversion REJECTED {symbol}: calculate_mean_reversion_levels returned None")
            return None
        
        #  Liquidity check
        budget = _calc_dynamic_budget(symbol, ctx)
        lg = liquidity_gate_safe(symbol, levels["side"], notional_usd=budget)
        if not (lg.get("ok") if isinstance(lg, dict) else lg):
            LOGGER.info(f"propose_mean_reversion REJECTED {symbol}: liquidity_gate failed")
            return None
        
        # 📊 Calculate MI Score with strategy-aware scoring
        from utils.market_intelligence import MarketIntelligence
        mi = MarketIntelligence()
        mi_score = mi.calculate_quality_score(ctx, strategy="mean_reversion")
        
        # 📊 Calculate SO Score
        so_score = 7.0  # Default conservative score for mean-reversion
        
        # 💰 DYNAMIC SIZING: Calculate optimal leverage and position size
        try:
            from utils.binance_client import _init_client
            cli = _init_client()
            if cli:
                acc_info = cli.futures_account()
                account_equity = float(acc_info.get("totalWalletBalance", 10000.0)) if acc_info else 10000.0
            else:
                account_equity = 10000.0
        except Exception:
            account_equity = 10000.0
        
        quality_score = mi_score
        volatility = (ctx.get("filters") or {}).get("vol_regime", "medium") or "medium"
        market_condition = ctx.get("_market_condition")
        
        dynamic_sizing_engine = get_dynamic_sizing_engine()
        sizing = dynamic_sizing_engine.calculate_position(
            quality_score=quality_score,
            risk_reward=float(levels["rr"]),
            ai_confidence=float(levels.get("win_rate_expected", 70.0)),
            volatility=volatility,
            account_equity=account_equity,
            market_regime=market_condition.regime if market_condition else "unknown",
            market_mood=market_condition.mood if market_condition else "neutral"
        )
        
        leverage = sizing.leverage
        dynamic_budget = sizing.size_usd / leverage
        notional = sizing.size_usd
        
        LOGGER.info(
            f"✅ MEAN-REVERSION PROPOSAL {symbol}: {levels['side']} @ {levels['entry']:.4f}, "
            f"TP={levels['tp2']:.4f}, SL={levels['sl']:.4f}, RR={levels['rr']:.2f}, "
            f"VWAP={levels['vwap']:.4f}, Dev={levels['deviation_pct']:.2f}%, "
            f"MI={mi_score:.1f}, SO={so_score:.1f}"
        )
        LOGGER.info(
            f"💰 Dynamic Sizing: {symbol} {levels['side']} → "
            f"Leverage={leverage}x, Budget=${dynamic_budget:.2f}, Position=${notional:.2f}"
        )
        
        payload = {
            "trade_id": f"mr{int(time.time())}{random.randint(100,999)}",
            "trade_type": "MEAN_REVERSION",
            "symbol": symbol,
            "side": levels["side"],
            "market": "futures",
            "current_price": float(price),
            "entry": float(levels["entry"]),
            "sl": float(levels["sl"]),
            "tp1": float(levels["tp1"]),
            "tp2": float(levels["tp2"]),
            "tp3": None,
            "rr": float(levels["rr"]),
            "success_pct": float(levels.get("win_rate_expected", 70.0)),
            "reason": levels.get("reason", "Mean-Reversion VWAP Strategy"),
            "leverage": leverage,  # ✅ DYNAMIC LEVERAGE (was hardcoded 6x)
            "budget_usd": float(dynamic_budget),
            "notional_usd": float(notional),
            "strategy": "mean_reversion",
            "strategy_type": "mean_reversion",
            "win_rate_expected": float(levels.get("win_rate_expected", 70.0)),
            "mi_score": float(mi_score),
            "so_score": float(so_score),
            "chat_id": TELEGRAM_CHAT_ID or None,
        }
        return payload
        
    except Exception as e:
        LOGGER.warning(f"propose_mean_reversion ERROR {symbol}: {e}")
        return None

# ---------------- Cycle ----------------
async def process_cycle():
    # פרופיל שעות → קובע topK, cooldown, rr_bonus (rr_bonus כבר טופל ב-Context)
    hp = hours_profile_now()
    topk = max(1, int(hp.get("topk", 12)))
    cooldown_min = max(3, int(hp.get("cooldown_min", 12)))
    cooldown_sec = cooldown_min * 60

    # 💰 MARGIN GUARD: Check available balance BEFORE scanning
    # This prevents generating proposals when funds are locked
    try:
        from utils.binance_client import futures_balance
        bals = await futures_balance() or []
        available = 0.0
        for a in bals:
            if str(a.get("asset", "")).upper() == "USDT":
                available = float(a.get("availableBalance") or a.get("available") or 0.0)
                break
        
        # Use 1x MIN budget as safety buffer for dynamic sizing
        # Changed from 2.0x to 1.0x to allow trading with lower balances
        min_budget = float(os.getenv("BUDGET_MIN_USDT", "10.0"))
        safety_buffer = min_budget * 1.0  # $10 minimum for realistic trades
        if available < safety_buffer:
            LOGGER.warning(
                f"⏸️ CYCLE PAUSED: Insufficient free margin (${available:.2f} < ${safety_buffer:.2f}). "
                f"Skipping entire scan cycle to avoid proposal spam. "
                f"Will resume when funds available."
            )
            return  # Skip entire cycle
    except Exception as e:
        LOGGER.debug(f"Margin check failed (proceeding anyway): {e}")

    # בנה Pool חכם (משקלול איכות+היסטוריית winrate)
    # 🎯 Two-Tier Strategy: High-quality core (6+) + Exploratory symbols (4-5)
    # Smart Filter stage 2 will still block <6.0 setups, but we scan 50 symbols for market breadth
    try:
        pool_syms = build_symbol_pool(k=topk, min_quality=4, include_anchor=True, include_shorts=True, balanced=True)  # 🔄 Lowered to 4 for market coverage
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

    async def maybe_emit(ttype: str, payload: Optional[Dict[str, Any]], ctx: Optional[Dict[str, Any]] = None):
        nonlocal accepted
        if not payload:
            return
        
        # 💰 CHECK AVAILABLE MARGIN: Skip proposals if insufficient funds
        available = 0.0  # Initialize before try block
        try:
            from utils.binance_client import futures_balance
            bals = futures_balance() or []
            for a in bals:
                if str(a.get("asset", "")).upper() == "USDT":
                    available = float(a.get("availableBalance") or a.get("available") or 0.0)
                    break
            
            # Use 1x MIN budget as safety buffer for dynamic sizing
            # Changed from 2.0x to 1.0x to allow trading with lower balances
            min_budget = float(os.getenv("BUDGET_MIN_USDT", "10.0"))
            safety_buffer = min_budget * 1.0  # $10 minimum for realistic trades
            if available < safety_buffer:
                LOGGER.warning(
                    f"⏸️ Insufficient margin (${available:.2f} < ${safety_buffer:.2f}) - skipping proposals temporarily"
                )
                return
        except Exception as e:
            LOGGER.debug(f"Margin check failed (proceeding anyway): {e}")
        
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
        
        # 🎯 SMART 3-STAGE FILTER: Check quality BEFORE expensive AI calls (95% cost reduction)
        try:
            from utils.smart_filter import smart_pre_filter
            
            # Use ctx if available, otherwise build minimal context from payload
            filter_ctx = ctx if ctx else {
                "symbol": symbol,
                "price": payload.get("entry"),
                "volume": payload.get("volume", 0),
                "volume_sma_20": payload.get("volume_sma_20", 1000000),
                "rsi": payload.get("rsi", 50),
                "adx": payload.get("adx", 25),
                "atr_percent": payload.get("atr_percent", 2.0),
                "bb_upper": payload.get("bb_upper", payload.get("entry", 100) * 1.02),
                "bb_lower": payload.get("bb_lower", payload.get("entry", 100) * 0.98),
                "ema_20": payload.get("entry")
            }
            
            filter_result = smart_pre_filter(symbol, filter_ctx)
            
            if not filter_result["passed"]:
                LOGGER.info(
                    f"🚫 Smart Filter BLOCKED {symbol} at Stage {filter_result['stage']}: "
                    f"{filter_result['reason']} (quality={filter_result['quality_score']:.1f}/10)"
                )
                return  # Skip AI consensus entirely - HUGE cost savings!
            
            # Store quality score in payload for logging
            payload["quality_score"] = filter_result["quality_score"]
            LOGGER.info(f"✅ Smart Filter PASSED {symbol} - Quality={filter_result['quality_score']:.1f}/10, proceeding to AI consensus")
            
        except Exception as e:
            LOGGER.warning(f"⚠️ Smart Filter error for {symbol}: {e} - proceeding to AI consensus anyway")
            payload["quality_score"] = 6.0  # Default
        
        # 🧠 AI CONSENSUS: Validate proposal with 3 AI Brains (≥2/3 required)
        # This applies to ALL proposal types: MEAN_REVERSION, GRID, FUTURES, SPOT
        # ONLY called if Smart Filter PASSED (10% of proposals)
        try:
            from utils.ai_decision_maker import AIConsensusEngine
            
            consensus_engine = AIConsensusEngine()
            
            # Extract scores from payload
            mi_score = payload.get("mi_score", 6.0)
            so_score = payload.get("so_score", 6.0)
            strategy_type = payload.get("strategy_type", "mean_reversion" if ttype == "MEAN_REVERSION" else "trend_following")
            
            # Build scout_data with CORRECT structure that get_consensus expects
            scout_data = {
                "symbol": symbol,
                "strategy": strategy_type,
                
                # Market Scanner (Market Intelligence)
                "market_scanner": {
                    "score": mi_score,
                    "regime": payload.get("regime", "UNKNOWN"),
                    "reasoning": f"{ttype} strategy with MI score {mi_score:.1f}",
                    "quality_score": mi_score
                },
                
                # Technical Analyst (Strategy Orchestrator)
                "technical_analyst": {
                    "score": so_score,
                    "strategy": strategy_type,
                    "reasoning": f"Setup score {so_score:.1f} for {strategy_type}",
                    "signals": []
                },
                
                "avg_score": (mi_score + so_score) / 2.0,
                
                # Trade parameters
                "entry": payload.get("entry"),
                "sl": payload.get("sl"),
                "tp1": payload.get("tp1"),
                "tp2": payload.get("tp2"),
                "tp3": payload.get("tp3"),
                "rr": payload.get("rr"),
                "leverage": payload.get("leverage", 5),
                "budget_usd": size_usd,
                "trade_type": ttype,
                
                # Additional metadata
                "min_rr": payload.get("min_rr", 1.1),
                "sl_atr_mult": payload.get("sl_atr_mult", 1.5),
                "tp_rr": payload.get("tp_rr", 1.5),
            }
            
            # Get wallet state for AI Consensus
            wallet_state = {"available_balance": available}
            
            # Use ctx if provided, otherwise build minimal context
            market_data = ctx or {"symbol": symbol, "price": payload.get("entry")}
            
            LOGGER.info(f"🧠 Requesting consensus from 5 AI Brains for {symbol} ({ttype})...")
            
            consensus_result = await consensus_engine.get_consensus(
                scout_data=scout_data,
                market_data=market_data,
                wallet_state=wallet_state
            )
            
            # Log consensus
            LOGGER.info(
                f"🗳️ CONSENSUS [{symbol}]: {consensus_result['approve_count']}/3 APPROVE | "
                f"Decision: {consensus_result['final_vote']} | "
                f"Avg Score: {consensus_result['final_score']:.1f}/10"
            )
            
            for vote in consensus_result["brain_votes"]:
                LOGGER.info(
                    f"  {vote['brain']}: {vote['vote']} ({vote['score']:.1f}/10) - {vote['reasoning'][:80]}..."
                )
            
            # If REJECT, stop here
            if consensus_result["final_vote"] == "REJECT":
                LOGGER.info(f"❌ REJECTED by AI consensus: {symbol} ({ttype})")
                return
            
            # Update payload with consensus scores
            payload["consensus_score"] = consensus_result["final_score"]
            payload["consensus_votes"] = f"{consensus_result['approve_count']}/3"
            
            LOGGER.info(f"✅ APPROVED by AI consensus: {symbol} ({ttype}) - {consensus_result['approve_count']}/3 votes")
            
        except Exception as e:
            LOGGER.error(f"⚠️ AI Consensus failed for {symbol} ({ttype}): {e}")
            # If AI Consensus fails, reject the proposal for safety
            LOGGER.info(f"❌ REJECTED due to consensus failure: {symbol} ({ttype})")
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
        
        # 🎯 STRATEGY ORCHESTRATOR: Decide which strategy to use
        # First, analyze market to get market_condition
        try:
            from utils.market_intelligence import get_market_intelligence
            mi_engine = get_market_intelligence()
            
            # Quick market analysis to determine strategy
            if "multi_tf" in ctx and ctx["multi_tf"]:
                multi_tf_contexts = {}
                for tf_name, tf_data in ctx["multi_tf"].items():
                    multi_tf_contexts[tf_name] = tf_data
                market_condition = mi_engine.analyze_multi_tf(multi_tf_contexts)
            else:
                market_condition = mi_engine.analyze_market(ctx)
            
            # Get strategy recommendation
            orchestrator = get_strategy_orchestrator()
            strategy_config = await orchestrator.select_strategy(market_condition, sym, ctx)
            
            # 🚀 EXECUTE STRATEGY BASED ON ORCHESTRATOR DECISION
            if strategy_config.grid_mode and SUGGEST_GRID:
                # Try GRID Strategy first
                try:
                    LOGGER.info(f"🎯 {sym}: Attempting GRID strategy (range required ≥2%)")
                    p = await propose_grid(sym, ctx)
                    if p:
                        await maybe_emit("GRID", p, ctx)
                    else:
                        # 🔄 FALLBACK CHAIN: GRID → Mean-Reversion → Futures
                        LOGGER.info(f"🔄 {sym}: GRID unavailable (no range), trying Mean-Reversion")
                        mr_p = await propose_mean_reversion(sym, ctx)
                        if mr_p:
                            LOGGER.info(f"✅ {sym}: Mean-Reversion viable for CHOPPY/<2% market")
                            await maybe_emit("MEAN_REVERSION", mr_p, ctx)
                        else:
                            # Final fallback to Futures/Scalping
                            LOGGER.info(f"🔄 {sym}: Mean-Reversion unavailable, falling back to FUTURES")
                            if SUGGEST_FUTURES:
                                try:
                                    p = await propose_futures(sym, ctx, success_floor)
                                    await maybe_emit("FUTURES", p, ctx)
                                except Exception as e:
                                    LOGGER.exception(f"propose_futures fallback error {sym}: {e}")
                except Exception as e:
                    LOGGER.info(f"propose_grid ERROR {sym}: {e}")
                    # Fallback to FUTURES on error
                    if SUGGEST_FUTURES:
                        try:
                            p = await propose_futures(sym, ctx, success_floor)
                            await maybe_emit("FUTURES", p, ctx)
                        except Exception as e2:
                            LOGGER.exception(f"propose_futures fallback error {sym}: {e2}")
            
            elif strategy_config.mean_reversion_mode:
                # Mean-Reversion Strategy (VWAP-based, deterministic)
                try:
                    LOGGER.info(f"🎯 {sym}: Attempting Mean-Reversion strategy (VWAP-based, range <2%)")
                    mr_p = await propose_mean_reversion(sym, ctx)
                    if mr_p:
                        LOGGER.info(f"✅ {sym}: Mean-Reversion proposal generated")
                        await maybe_emit("MEAN_REVERSION", mr_p, ctx)
                    else:
                        # Fallback to Futures/Scalping
                        LOGGER.info(f"🔄 {sym}: Mean-Reversion unavailable, falling back to FUTURES")
                        if SUGGEST_FUTURES:
                            try:
                                p = await propose_futures(sym, ctx, success_floor)
                                await maybe_emit("FUTURES", p, ctx)
                            except Exception as e:
                                LOGGER.exception(f"propose_futures fallback error {sym}: {e}")
                except Exception as e:
                    LOGGER.info(f"propose_mean_reversion ERROR {sym}: {e}")
                    # Fallback to FUTURES on error
                    if SUGGEST_FUTURES:
                        try:
                            p = await propose_futures(sym, ctx, success_floor)
                            await maybe_emit("FUTURES", p, ctx)
                        except Exception as e2:
                            LOGGER.exception(f"propose_futures fallback error {sym}: {e2}")
            
            elif strategy_config.strategy_type == "wait":
                # WAIT Mode - very selective
                LOGGER.info(f"⏸️ {sym}: WAIT mode - market uncertain, skipping for now")
                # Still try futures but with very high thresholds (handled by strategy_config)
                if SUGGEST_FUTURES:
                    try:
                        p = await propose_futures(sym, ctx, success_floor)
                        await maybe_emit("FUTURES", p, ctx)
                    except Exception as e:
                        LOGGER.exception(f"propose_futures error {sym}: {e}")
            
            else:
                # FUTURES strategies (Scalping, Momentum, Range-Bounce, Breakout)
                if SUGGEST_FUTURES:
                    try:
                        p = await propose_futures(sym, ctx, success_floor)
                        await maybe_emit("FUTURES", p, ctx)
                    except Exception as e:
                        LOGGER.exception(f"propose_futures error {sym}: {e}")
                
                # SPOT (if enabled)
                if SUGGEST_SPOT:
                    try:
                        p = await propose_spot(sym, ctx, success_floor)
                        await maybe_emit("SPOT", p, ctx)
                    except Exception as e:
                        LOGGER.debug("propose_spot error %s: %s", sym, e)
        
        except Exception as e:
            LOGGER.exception(f"Strategy orchestration error for {sym}: {e}")
            # Fallback to original behavior if orchestrator fails
            if SUGGEST_FUTURES:
                try:
                    p = await propose_futures(sym, ctx, success_floor)
                    await maybe_emit("FUTURES", p, ctx)
                except Exception as e2:
                    LOGGER.exception(f"propose_futures fallback error {sym}: {e2}")

    async def worker(sym: str):
        async with sem:
            await handle_symbol(sym)

    await asyncio.gather(*(worker(s) for s in symbols), return_exceptions=True)
    LOGGER.info("cycle finished: symbols=%d accepted=%d cap=%d", len(symbols), accepted, cap_per_cycle)

async def main():
    # ========== MODULE VERSION VERIFICATION ==========
    # Verify get_klines module is loaded correctly (detect caching issues)
    try:
        from utils.get_klines import KLINES_VERSION, KLINES_MODULE_FILE, KLINES_FIX_DESCRIPTION, _get_module_hash
        LOGGER.info(f"✅ get_klines verification: VERSION={KLINES_VERSION}, FILE={KLINES_MODULE_FILE}")
        LOGGER.info(f"✅ get_klines module hash: {_get_module_hash()}, FIX={KLINES_FIX_DESCRIPTION}")
        
        # Verify we're using the correct version (no startTime caching)
        if KLINES_VERSION != "3.0.0":
            LOGGER.error(f"❌ STALE get_klines module detected! Expected v3.0.0, got {KLINES_VERSION}")
            LOGGER.error(f"❌ This means Gunicorn workers are using CACHED old code!")
            LOGGER.error(f"❌ ACTION REQUIRED: Restart all workers to load updated code")
        else:
            LOGGER.info(f"✅ get_klines module is up-to-date (v{KLINES_VERSION})")
    except Exception as e:
        LOGGER.error(f"❌ Failed to verify get_klines module version: {e}")
    
    # Log feature toggles at startup
    LOGGER.info(f"🚀 Auto-suggest started: FUTURES={SUGGEST_FUTURES}, SPOT={SUGGEST_SPOT}, GRID={SUGGEST_GRID}")
    if not SUGGEST_ENABLED:
        LOGGER.warning("Auto-suggest disabled (TRADE_AUTO_SUGGEST=0)")
    interval_sec = int(float(os.getenv("SUGGEST_INTERVAL_SEC","300")))   # 5m דיפולט (was 600s/10m)
    LOGGER.info(f"🔄 Auto Scanner starting with interval={interval_sec}s ({interval_sec/60:.1f} minutes)")
    
    while True:
        try:
            if SUGGEST_ENABLED:
                # Track cycle cost
                from utils.cost_tracker import get_cost_tracker
                tracker = get_cost_tracker()
                
                cycle_start = time.time()
                await process_cycle()
                cycle_duration = time.time() - cycle_start
                
                # Reset cycle counter and log cost
                cycle_cost = tracker.reset_cycle()
                LOGGER.info(
                    f"💰 Cycle completed in {cycle_duration:.1f}s | "
                    f"Cost: ${cycle_cost:.4f} | "
                    f"Daily Total: ${tracker.daily_total:.3f}"
                )
            
            await asyncio.sleep(interval_sec)
        except Exception as e:
            LOGGER.exception("cycle error: %s", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
















