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
from utils.risk_profile_manager import get_risk_profile_manager  # ← Balance-Tiered Risk Profiles (MetaBrain v9.1)
from utils.multi_target_tp import get_multi_target_tp  # ← Multi-Target TP System (MetaBrain v9.1)
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

def _indicators_from_df(interval: str, df) -> Dict[str, Any]:
    """
    🎯 HELPER: Calculate all indicators from a DataFrame
    
    Args:
        interval: Timeframe (e.g., "15m", "1h", "4h")
        df: Pandas DataFrame with OHLCV data
        
    Returns:
        Dict with all calculated indicators
    """
    try:
        from utils.indicators import rsi, adx, atr, macd, bollinger_bands, ema
        
        if df is None or df.empty or len(df) < 50:
            LOGGER.debug(f"⚠️ Insufficient data in DataFrame ({len(df) if df is not None else 0} candles)")
            return {}
        
        close = df["close"]
        price = float(close.iloc[-1])
        
        # Calculate all indicators from DataFrame
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
        
        # Calculate Bollinger Bands width percentage (critical for regime detection)
        bb_upper_val = float(bb_upper.iloc[-1]) if not bb_upper.empty else price * 1.02
        bb_mid_val = float(bb_mid.iloc[-1]) if not bb_mid.empty else price
        bb_lower_val = float(bb_lower.iloc[-1]) if not bb_lower.empty else price * 0.98
        
        bb_width_pct = ((bb_upper_val - bb_lower_val) / bb_mid_val * 100.0) if bb_mid_val > 0 else 5.0
        
        # Calculate EMA slope (% change over last 10 periods) for trend strength
        ema20_slope = 0.0
        ema50_slope = 0.0
        if len(ema20) >= 10:
            ema20_current = float(ema20.iloc[-1])
            ema20_past = float(ema20.iloc[-10])
            ema20_slope = ((ema20_current - ema20_past) / ema20_past * 100.0) if ema20_past > 0 else 0.0
        
        if len(ema50) >= 10:
            ema50_current = float(ema50.iloc[-1])
            ema50_past = float(ema50.iloc[-10])
            ema50_slope = ((ema50_current - ema50_past) / ema50_past * 100.0) if ema50_past > 0 else 0.0
        
        # Calculate 24H high/low for AI Strategy Consensus
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
            "bb_upper": round(bb_upper_val, 6),
            "bb_mid": round(bb_mid_val, 6),
            "bb_lower": round(bb_lower_val, 6),
            "bb_width_pct": round(bb_width_pct, 2),
            "ema_20": round(float(ema20.iloc[-1]), 6) if not ema20.empty else price,
            "ema_50": round(float(ema50.iloc[-1]), 6) if not ema50.empty else price,
            "ema20_slope": round(ema20_slope, 3),
            "ema50_slope": round(ema50_slope, 3),
            "volume": float(df["volume"].iloc[-1]),
            "volume_sma_20": round(float(volume_sma_20.iloc[-1]), 2) if not volume_sma_20.empty else 1000000
        }
        
        return indicators
        
    except Exception as e:
        LOGGER.error(f"❌ Failed to calculate indicators from DataFrame: {e}")
        return {}

async def _fetch_real_indicators(symbol: str, interval: str = "15m", limit: int = 200, df=None) -> Dict[str, Any]:
    """
    🎯 LIVE BINANCE DATA - Fetch real klines and calculate all indicators
    
    Args:
        symbol: Trading symbol (e.g., BTCUSDT)
        interval: Timeframe (e.g., "15m", "1h", "4h")
        limit: Number of candles to fetch
        df: Optional pre-fetched DataFrame (if provided, skips get_klines call)
        
    Returns:
        Dict with all calculated indicators
    """
    try:
        from utils.get_klines import get_klines
        
        # If DataFrame provided, use it directly; otherwise fetch from Binance
        if df is None:
            df = await get_klines(symbol, interval=interval, limit=limit, market_type="futures")
        
        if df is None or df.empty or len(df) < 50:
            LOGGER.warning(f"⚠️ {symbol} [{interval}]: Insufficient klines data ({len(df) if df is not None else 0} candles)")
            return {}
        
        # Use extracted helper function
        indicators = _indicators_from_df(interval, df)
        
        if indicators:
            LOGGER.info(
                f"📊 LIVE Indicators [{symbol}] [{interval.upper()}]: "
                f"RSI={indicators['rsi']:.1f}, ADX={indicators['adx']:.1f}, "
                f"ATR={indicators['atr_percent']:.2f}%, MACD={indicators['macd']:.4f}"
            )
        
        return indicators
        
    except Exception as e:
        LOGGER.error(f"❌ Failed to fetch real indicators for {symbol} [{interval}]: {e}")
        return {}

async def _build_multi_tf_snapshot(symbol: str) -> Dict[str, Dict[str, Any]]:
    """
    🎯 MULTI-TIMEFRAME SNAPSHOT: Fetch and analyze 15M + 1H + 4H data
    
    Args:
        symbol: Trading symbol (e.g., BTCUSDT)
        
    Returns:
        Dict mapping timeframe -> indicators
        Example: {"15m": {...}, "1h": {...}, "4h": {...}}
    """
    try:
        # Get MultiTFContextManager instance
        tf_manager = MultiTFContextManager()
        
        # Fetch all timeframes in parallel (optimized with caching)
        intervals = ["15m", "1h", "4h"]
        limit = 240  # Sufficient for all indicators across all timeframes
        
        LOGGER.info(f"🔄 Fetching multi-TF data for {symbol}: {intervals}")
        
        # Batch fetch all timeframes (single operation, parallelized internally)
        multi_tf_data = await tf_manager.fetch_batch_multi_tf(
            symbols=[symbol],
            intervals=intervals,
            limit=limit,
            force_refresh=False  # Use cache when available
        )
        
        # Extract data for this symbol
        symbol_data = multi_tf_data.get(symbol.upper(), {})
        
        if not symbol_data:
            LOGGER.warning(f"⚠️ No multi-TF data returned for {symbol}")
            return {}
        
        # Calculate indicators for each timeframe
        result = {}
        for interval in intervals:
            df = symbol_data.get(interval)
            if df is not None and not df.empty:
                indicators = _indicators_from_df(interval, df)
                if indicators:
                    result[interval] = indicators
                    LOGGER.debug(
                        f"✅ {symbol} [{interval.upper()}]: "
                        f"Price={indicators.get('price', 0):.4f}, "
                        f"RSI={indicators.get('rsi', 0):.1f}, "
                        f"ADX={indicators.get('adx', 0):.1f}"
                    )
                else:
                    LOGGER.warning(f"⚠️ {symbol} [{interval}]: Failed to calculate indicators")
            else:
                LOGGER.warning(f"⚠️ {symbol} [{interval}]: No DataFrame available")
        
        if result:
            LOGGER.info(
                f"✅ Multi-TF snapshot built for {symbol}: "
                f"{len(result)}/{len(intervals)} timeframes ready"
            )
        else:
            LOGGER.warning(f"⚠️ {symbol}: No valid timeframe data in multi-TF snapshot")
        
        return result
        
    except Exception as e:
        LOGGER.error(f"❌ Failed to build multi-TF snapshot for {symbol}: {e}", exc_info=True)
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
ALERT_INGEST_URL = os.getenv("ALERT_INGEST_URL","").strip()  # No default - use standalone mode if not set
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET","").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", os.getenv("ADMIN_CHAT_ID","")).strip()

SUGGEST_ENABLED   = os.getenv("TRADE_AUTO_SUGGEST","1").lower() in ("1","true","yes")
POOL_PER_CYCLE    = int(os.getenv("SYMBOLS_PER_CYCLE","50"))  # 🚀 Increased from 10 to 50 for better market coverage
MAX_CONCURRENCY   = int(os.getenv("OPENAI_MAX_CONCURRENCY","2"))
CAP_PER_CYCLE_ENV = int(os.getenv("SUGGEST_CAP_PER_CYCLE","5"))

SUCCESS_PCT_MIN   = float(os.getenv("SUCCESS_PCT_MIN","70"))

# תקציב בסיס (ישמש כפולבק אם הדינמי כבוי)
BUDGET_USD_FALLBK = float(os.getenv("MAX_TRADE_BUDGET","100"))  # Fallback OK - dynamic budget system handles minimums

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
def validate_rr_smart(rr_ratio: float, min_rr: float, consensus_result: Optional[Dict], symbol: str) -> Tuple[bool, str]:
    """
    🎯 Smart RR Validation with regime-aware dynamic thresholds
    
    Args:
        rr_ratio: Calculated RR from rr_from_levels()
        min_rr: Dynamic minimum RR from market_condition.min_rr_threshold
        consensus_result: AI consensus data from ctx["_consensus_result"]
        symbol: Symbol name for logging
        
    Returns:
        (is_valid, reason_message)
    
    Logic:
        1. HARD FLOOR (0.8): Absolute safety net - reject if RR < 0.8
        2. AUTO APPROVE (≥min_rr): Meets regime-specific requirement
        3. CONSENSUS ZONE (0.8 to min_rr): Requires 2/3 AI consensus (66%)
    """
    HARD_FLOOR = 0.8
    
    # 1. HARD FLOOR - absolute minimum safety net
    if rr_ratio < HARD_FLOOR:
        return False, f"HARD_FLOOR_REJECT: RR={rr_ratio:.3f} < {HARD_FLOOR}"
    
    # 2. AUTO APPROVE - meets dynamic regime requirement
    if rr_ratio >= min_rr:
        return True, f"AUTO_APPROVE: RR={rr_ratio:.3f} ≥ {min_rr:.2f}"
    
    # 3. CONSENSUS ZONE (0.8 to min_rr)
    # Check if consensus data is available
    if not consensus_result:
        return False, f"NO_CONSENSUS_DATA: RR={rr_ratio:.3f} < {min_rr:.2f}, consensus unavailable"
    
    approve_count = consensus_result.get("approve_count", 0)
    if approve_count >= 2:
        return True, f"CONSENSUS_APPROVE: RR={rr_ratio:.3f}, {approve_count}/3 AI approved (66% majority)"
    else:
        return False, f"INSUFFICIENT_CONSENSUS: RR={rr_ratio:.3f}, only {approve_count}/3 AI approved (need ≥2 for 66%)"

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
        LOGGER.debug("CONTEXT_URL not set – using local context fallback")
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
    Enhanced local context fallback when Context API is unavailable.
    
    Fetches basic market data (price, range) from Binance for GRID/Mean-Reversion compatibility.
    Full indicators are calculated via _fetch_real_indicators later in the pipeline.
    """
    LOGGER.info(
        f"📡 Building enhanced local context for {len(symbols)} symbols (Context API unavailable)"
    )
    
    from utils.binance_client import _init_client
    
    out = {}
    cli = _init_client()
    
    if not cli:
        # Fallback to minimal context if Binance unavailable
        LOGGER.warning("Binance client unavailable - using minimal context")
        return {symbol: {"symbol": symbol, "interval": interval} for symbol in symbols}
    
    # Fetch 24h ticker data for all symbols (single API call)
    try:
        tickers = cli.futures_ticker()
        ticker_map = {t["symbol"]: t for t in tickers if t.get("symbol")}
    except Exception as e:
        LOGGER.warning(f"Failed to fetch tickers: {e}")
        ticker_map = {}
    
    # Load watchlist for quality scores
    from utils.watchlist_utils import load_watchlist
    
    try:
        watchlist = load_watchlist(min_quality=None)
        quality_map = {item["symbol"]: item.get("quality_score", 5) for item in watchlist if item.get("symbol")}
    except Exception as e:
        LOGGER.warning(f"Failed to load watchlist: {e}")
        quality_map = {}
    
    # Build context with price + range + quality data
    for symbol in symbols:
        ticker = ticker_map.get(symbol)
        quality = quality_map.get(symbol, 5)  # Default quality = 5 (medium)
        
        if ticker:
            price = float(ticker.get("lastPrice", 0))
            high_24h = float(ticker.get("highPrice", 0))
            low_24h = float(ticker.get("lowPrice", 0))
            
            # Calculate range percentage
            range_pct = 0.0
            if low_24h > 0:
                range_pct = ((high_24h - low_24h) / low_24h) * 100
            
            out[symbol] = {
                "symbol": symbol,
                "interval": interval,
                "price": price,
                "close": price,
                "high_24h": high_24h,
                "low_24h": low_24h,
                "range_pct": range_pct,
                "filters": {
                    "quality": quality,
                    "quality_score": quality,
                }
            }
            LOGGER.debug(f"✅ {symbol}: price={price:.4f}, range={range_pct:.2f}%, quality={quality}")
        else:
            # Fallback to minimal context for this symbol
            out[symbol] = {
                "symbol": symbol, 
                "interval": interval,
                "filters": {
                    "quality": quality,
                    "quality_score": quality,
                }
            }
            LOGGER.debug(f"⚠️ {symbol}: no ticker data, using minimal context (quality={quality})")
    
    LOGGER.info(f"✅ Enhanced context built for {len(out)} symbols ({len([s for s in out.values() if 'price' in s])}/{len(symbols)} with price data)")
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
    "7. 🔴 DIRECTIONAL BIAS - CRITICAL FOR FUTURES! 🔴\n"
    "   Choose trade direction based on market mood (EMA alignment):\n"
    "\n"
    "   BEARISH Market (price < EMA20 < EMA50):\n"
    "   → PREFER SHORT trades! Look for resistance breakdowns, failed rallies\n"
    "   → Example: SHORT entry near resistance, SL above recent high, TP at support\n"
    "\n"
    "   BULLISH Market (price > EMA20 > EMA50):\n"
    "   → PREFER LONG trades! Look for support bounces, breakout continuations\n"
    "   → Example: LONG entry near support, SL below recent low, TP at resistance\n"
    "\n"
    "   NEUTRAL Market (mixed EMA signals):\n"
    "   → Use RSI + MACD for direction! Oversold→LONG, Overbought→SHORT\n"
    "\n"
    "   ⚠️ Trading AGAINST the trend is VERY RISKY - only for extreme reversals!\n"
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
    """
    Build user context with ALL technical data for AI proposal generation.
    Includes all indicators from _fetch_real_indicators + market intelligence.
    """
    # Extract market condition if available
    market_condition = ctx.get("_market_condition", {})
    
    data = {
        "symbol": symbol,
        # Price data
        "price": ctx.get("close") or ctx.get("price"),
        "close": ctx.get("close"),
        "high_24h": ctx.get("high_24h"),
        "low_24h": ctx.get("low_24h"),
        # Technical indicators (from _fetch_real_indicators)
        "rsi": ctx.get("rsi"),
        "adx": ctx.get("adx"),
        "atr": ctx.get("atr"),  # Absolute ATR value
        "atr_percent": ctx.get("atr_percent"),  # ATR as % of price
        "macd": ctx.get("macd"),
        "macd_signal": ctx.get("macd_signal"),
        "macd_hist": ctx.get("macd_hist"),
        "bb_upper": ctx.get("bb_upper"),
        "bb_mid": ctx.get("bb_mid"),
        "bb_lower": ctx.get("bb_lower"),
        "ema_20": ctx.get("ema_20"),
        "ema_50": ctx.get("ema_50"),
        # Volume metrics
        "volume": ctx.get("volume"),
        "volume_sma_20": ctx.get("volume_sma_20"),
        # Market intelligence
        "regime": market_condition.get("regime") if isinstance(market_condition, dict) else None,
        "mood": market_condition.get("mood") if isinstance(market_condition, dict) else None,
        "recommended_strategy": market_condition.get("recommended_strategy") if isinstance(market_condition, dict) else None,
        # Dynamic filters (flattened in ctx by _fetch_context_batch)
        "min_rr": ctx.get("min_rr"),
        "success_min": ctx.get("success_min"),
        "quality_min": ctx.get("quality_min")
    }
    return json.dumps(data, ensure_ascii=False)

def _parse_json_safe(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse JSON from LLM response, handling markdown code fences and extra text.
    Returns None if parsing fails completely.
    """
    if not text or not isinstance(text, str):
        return None
    
    # Strip whitespace
    text = text.strip()
    
    # Remove markdown code fences (```json ... ``` or ``` ... ```)
    if text.startswith("```"):
        # Find the first newline after opening fence
        first_newline = text.find("\n")
        if first_newline > 0:
            # Remove opening fence line
            text = text[first_newline + 1:]
        # Remove closing fence
        if text.endswith("```"):
            text = text[:-3].strip()
    
    # Try to extract JSON from text (in case there's commentary before/after)
    # Look for first { and last }
    json_start = text.find("{")
    json_end = text.rfind("}")
    
    if json_start >= 0 and json_end > json_start:
        text = text[json_start:json_end + 1]
    
    # Try parsing
    try:
        result = json.loads(text)
        # Validate it's a dict
        if isinstance(result, dict):
            return result
        return None
    except Exception as e:
        LOGGER.debug(f"JSON parse failed: {e}, text preview: {text[:100]}")
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
    
    sym = payload.get("symbol", "UNKNOWN")
    side = payload.get("side", "")
    
    # 🚀 STANDALONE MODE: If no webhook configured, execute directly via ExecutionBot
    if not ALERT_INGEST_URL or not WEBHOOK_HMAC_SECRET:
        LOGGER.info(
            f"🔧 No external webhook configured - executing {sym} {side} in STANDALONE mode"
        )
        
        try:
            from utils.execution_bot import ExecutionBot
            
            original_side = payload.get("side", "LONG")
            execution_side = "BUY" if original_side == "LONG" else "SELL"
            
            # 🔧 FIX: Use consensus_score as quality_score if quality_score missing
            quality_value = payload.get("quality_score") or payload.get("consensus_score")
            LOGGER.info(f"🔍 STANDALONE DEBUG {sym}: quality_score={quality_value}, keys={list(payload.keys())}")
            
            # 💰 DYNAMIC BUDGET FALLBACK: Use MIN budget if payload missing budget_usd
            min_budget_fallback = float(os.getenv("BUDGET_MIN_USDT", "25.0"))
            
            # 🔧 FIX: Use dynamic leverage from payload (calculated by Dynamic Sizing Engine)
            # Default to 5x (middle of 1-35x range) ONLY if payload missing leverage
            default_leverage = 5.0  # Middle of 1-35x range
            
            ticket = {
                "symbol": payload.get("symbol"),
                "side": execution_side,
                "budget_usd": payload.get("budget_usd") or payload.get("notional_usd", min_budget_fallback),
                "leverage": payload.get("leverage", default_leverage),  # 🔧 FIX: Dynamic leverage, not hardcoded 2x
                "entry": payload.get("entry") or payload.get("current_price"),
                "sl": payload.get("sl"),
                "tp": payload.get("tp1") or payload.get("tp"),
                "position_type": "MARKET",
                "quality": quality_value or 100.0,
                "score": quality_value or 100.0,
                "atr_pct": payload.get("atr_pct"),
                "vol": payload.get("vol"),
                "is_grid": payload.get("is_grid", False),
                "grid_min": payload.get("grid_min"),
                "grid_max": payload.get("grid_max"),
                "grid_levels": payload.get("grid_levels"),
                "metadata": {
                    "trade_type": payload.get("trade_type"),
                    "is_grid": payload.get("is_grid", False),
                    "grid_min": payload.get("grid_min"),
                    "grid_max": payload.get("grid_max"),
                    "grid_levels": payload.get("grid_levels"),
                    "grid_step_pct": payload.get("grid_step_pct"),
                    "grid_side": payload.get("grid_side"),
                    "consensus_score": payload.get("consensus_score"),
                    "quality_score": quality_value,  # ✅ Use calculated quality_value
                    "reason": payload.get("reason", ""),
                    "original_side": original_side,
                }
            }
            
            bot = ExecutionBot()
            result = await bot.open_position(ticket, source="auto_scanner_standalone")
            
            raw = result.get("raw", {})
            is_success = (
                result.get("status") in ("opened", "success") and
                raw.get("ok", False) is not False
            )
            
            if is_success:
                LOGGER.info(f"✅ STANDALONE execution successful: {sym} {original_side}")
                
                # 📱 Send comprehensive Telegram notification for standalone trade entry
                try:
                    await send_standalone_entry_notification(payload, result, raw)
                except Exception as tg_err:
                    LOGGER.warning(f"⚠️ Telegram notification failed (trade executed successfully): {tg_err}")
                
                return True
            else:
                reason = result.get("reason") or raw.get("error", "Unknown error")
                LOGGER.error(f"❌ STANDALONE execution failed: {sym} {original_side} - {reason}")
                return False
                
        except Exception as exec_err:
            LOGGER.error(f"❌ STANDALONE execution error for {sym} {side}: {exec_err}")
            return False
    
    # 📡 WEBHOOK MODE: Send to external alert ingest service
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
        LOGGER.error(
            f"❌ Webhook emit failed for {sym} {side}: {type(e).__name__}: {e}\n"
            f"   URL: {ALERT_INGEST_URL}\n"
            f"   Payload keys: {list(payload.keys())}"
        )
        return False

# ---------------- Telegram Standalone Notifications ----------------
async def send_standalone_entry_notification(payload: Dict[str, Any], result: Dict[str, Any], raw: Dict[str, Any]) -> None:
    """
    📱 Send comprehensive Telegram notification for standalone trade entry
    
    Includes:
    - Quality score (0-10)
    - Profit expectations (TP levels with % gains)
    - Entry timing and market regime
    - Leverage and budget allocation
    - Entry/SL/TP prices
    """
    try:
        import httpx
        from datetime import datetime
        
        BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        
        if not BOT_TOKEN or not CHAT_ID:
            LOGGER.debug("Telegram not configured - skipping notification")
            return
        
        # Extract data from payload
        symbol = payload.get("symbol", "UNKNOWN")
        side = payload.get("side", "LONG")
        # 🔧 FIX: Use consensus_score as fallback if quality_score missing
        quality_score = payload.get("quality_score") or payload.get("consensus_score", 0.0)
        consensus_score = payload.get("consensus_score", 0.0)
        
        # Entry details
        entry_price = raw.get("entry_price") or payload.get("entry") or payload.get("current_price", 0.0)
        sl_price = raw.get("sl_price") or payload.get("sl", 0.0)
        tp_prices = raw.get("tp_prices", []) or [payload.get("tp1"), payload.get("tp2"), payload.get("tp3")]
        tp_prices = [tp for tp in tp_prices if tp]  # Filter None values
        
        # Financial details
        leverage = payload.get("leverage", raw.get("leverage", 1))
        budget_recommended = payload.get("budget_usd") or payload.get("notional_usd", 0.0)
        
        # Extract ACTUAL investment from execution result
        actual_investment = raw.get("actual_investment") or result.get("actual_investment")
        if not actual_investment:
            # Fallback: calculate from grid_orders if available
            grid_orders = raw.get("grid_orders", [])
            if grid_orders:
                # For GRID: sum up all order notionals
                actual_investment = sum(
                    float(order.get("qty", 0)) * float(order.get("price", 0))
                    for order in grid_orders
                ) / leverage if leverage else 0
            else:
                # Fallback to recommended
                actual_investment = budget_recommended
        
        investment_display = budget_recommended * leverage if leverage and budget_recommended else 0.0
        
        # Strategy and regime
        trade_type = payload.get("trade_type", "UNKNOWN")
        is_grid = payload.get("is_grid", False)
        reason = payload.get("reason", "")
        market_regime = payload.get("market_regime", "UNKNOWN")
        
        # Calculate expected profits
        profit_expectations = []
        if entry_price and tp_prices:
            for i, tp in enumerate(tp_prices[:3], 1):
                if tp and entry_price:
                    pct_gain = ((tp - entry_price) / entry_price * 100) if side == "LONG" else ((entry_price - tp) / entry_price * 100)
                    profit_expectations.append(f"TP{i}: {tp:.6f} (+{pct_gain:.2f}%)")
        
        # Build message
        side_emoji = "🟢" if side == "LONG" else "🔴"
        quality_emoji = "🌟" if quality_score >= 8 else "✅" if quality_score >= 6 else "⚠️"
        strategy_badge = "🎯 GRID" if is_grid else f"📊 {trade_type}"
        
        message = f"""
{side_emoji} <b>New {side} Position Opened</b> {quality_emoji}

━━━━━━━━━━━━━━━━━━━━
<b>📍 {symbol}</b>
{strategy_badge} | 🧠 Quality: <b>{quality_score:.1f}/10</b>

💰 <b>Entry Details:</b>
• Entry: <code>{entry_price:.6f}</code>
• Stop Loss: <code>{sl_price:.6f}</code> ({((sl_price - entry_price) / entry_price * 100):.2f}%)
• Leverage: <b>x{leverage}</b>
• Budget: ${budget_recommended:.2f} (${actual_investment:.2f} position)

🎯 <b>Profit Targets:</b>
{chr(10).join(f"• {exp}" for exp in profit_expectations) if profit_expectations else "• Not set"}

📊 <b>Market Analysis:</b>
• Regime: <code>{market_regime}</code>
• Consensus: {consensus_score:.1f}/10
• Reason: {reason[:80]}...

⏰ <b>Entry Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC
━━━━━━━━━━━━━━━━━━━━
🤖 <i>Standalone Auto Scanner</i>
""".strip()
        
        # Send to Telegram
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                api_url,
                json={
                    "chat_id": CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                }
            )
            
            if response.status_code == 200:
                LOGGER.info(f"✅ Telegram notification sent for {symbol} {side}")
            else:
                LOGGER.warning(f"⚠️ Telegram API returned {response.status_code}: {response.text[:200]}")
                
    except Exception as e:
        LOGGER.error(f"❌ Failed to send Telegram notification: {e}", exc_info=True)

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
    # If indicators missing OR price/volume data is zero/missing, fetch REAL data from Binance
    needs_fetch = (
        not ctx.get("adx") or not ctx.get("rsi") or
        not ctx.get("close") or float(ctx.get("close", 0)) <= 0 or
        not ctx.get("high_24h") or float(ctx.get("high_24h", 0)) <= 0 or
        not ctx.get("low_24h") or float(ctx.get("low_24h", 0)) <= 0 or
        not ctx.get("volume") or float(ctx.get("volume", 0)) <= 0
    )
    
    if needs_fetch:
        LOGGER.info(f"📡 {symbol}: Fetching LIVE indicators from Binance (missing or zero data detected)")
        real_indicators = await _fetch_real_indicators(symbol, interval="15m", limit=200)
        if real_indicators:
            ctx.update(real_indicators)
            LOGGER.info(f"✅ {symbol}: LIVE indicators fetched successfully (close={ctx.get('close')}, ATR={ctx.get('atr_percent')}%)")
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
        "min_quality": strategy_config.min_quality,  # ← DYNAMIC quality threshold (tier-adjusted)
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
    
    LOGGER.info(f"🧠 Requesting consensus from 3 AI Brains for {symbol}...")
    
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
    LOGGER.info(f"🔍 User Context sent to DeepSeek [{symbol}]: {user_prompt[:500]}...")
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
            LOGGER.info(f"📝 DeepSeek raw response for {symbol}: {content[:300]}...")
            data = _parse_json_safe(content)
            if data:
                LOGGER.info(f"✅ DeepSeek generated proposal for {symbol}: {data}")
            else:
                LOGGER.warning(f"⚠️ DeepSeek response parsing failed for {symbol}")
        else:
            LOGGER.warning(f"❌ DeepSeek invalid response format for {symbol}: {response}")
    except Exception as e:
        LOGGER.warning(f"DeepSeek proposal generation failed for {symbol}: {e}")
    
    # Fallback to Grok if DeepSeek failed
    if data is None:
        try:
            from utils.xai_client import call_xai
            response = await call_xai(
                user_prompt,
                system=sys_prompt,
                temperature=0.7,
                max_tokens=400
            )
            
            if response:
                LOGGER.debug(f"📝 Grok raw response for {symbol}: {response[:200]}...")
                data = _parse_json_safe(response)
                if data:
                    LOGGER.info(f"✅ Grok generated proposal for {symbol} (DeepSeek fallback)")
                else:
                    LOGGER.warning(f"⚠️ Grok response parsing failed for {symbol}")
        except Exception as e:
            LOGGER.warning(f"Grok proposal generation failed for {symbol}: {e}")
    
    if data is None:
        LOGGER.warning(f"NO PROPOSAL from AI for {symbol}")
        return None
    
    # Parse and validate proposal (handle multiple field name formats)
    # Some AIs return "side", others return "direction"
    side = str(data.get("side") or data.get("direction", "")).upper()
    if for_spot and side != "LONG":
        side = "LONG"
    lev = _to_int(data.get("leverage"), default=10) or 10
    lev = max(SUGGEST_MIN_LEVERAGE, min(SUGGEST_MAX_LEVERAGE, lev))
    
    # Handle multiple field name formats for stop loss and take profit
    sl = _to_float(data.get("sl") or data.get("stop_loss"))
    tp1 = _to_float(data.get("tp1") or data.get("take_profit"))
    
    prop = {
        "symbol": symbol,
        "side": side if side in ("LONG","SHORT") else None,
        "entry": _to_float(data.get("entry")),
        "sl": sl,
        "tp1": tp1,
        "tp2": _to_float(data.get("tp2")),
        "tp3": _to_float(data.get("tp3")),
        "leverage": (1 if for_spot else lev),
        "success_pct": _to_float(data.get("success_pct") or data.get("confidence")),
        "reason": data.get("reason") or data.get("reasoning", ""),
    }
    if prop["side"] not in ("LONG","SHORT"):
        LOGGER.warning(f"❌ {symbol} REJECTED: Invalid side '{prop['side']}' (raw: {data.get('side')})")
        return None
    if prop["entry"] is None or prop["sl"] is None or prop["tp1"] is None:
        LOGGER.warning(f"❌ {symbol} REJECTED: Missing levels - entry={prop['entry']}, sl={prop['sl']}, tp1={prop['tp1']}")
        return None
    
    # 🎯 Smart RR Validation with AI Consensus support
    rr_check = rr_from_levels(prop["entry"], prop["sl"], prop["tp1"])
    
    if rr_check is None:
        LOGGER.warning(f"❌ {symbol} REJECTED: Unable to calculate RR ratio")
        return None
    
    # Get consensus data and dynamic threshold
    consensus_data = ctx.get("_consensus_result")
    min_rr = market_condition.min_rr_threshold
    
    # Use Smart RR Validation (HARD FLOOR 0.8, CONSENSUS ZONE, AUTO APPROVE)
    is_valid, reason = validate_rr_smart(
        rr_ratio=rr_check,
        min_rr=min_rr,
        consensus_result=consensus_data,
        symbol=symbol
    )
    
    if not is_valid:
        LOGGER.info(f"🚫 {symbol}: {reason} (regime={market_condition.regime}, mood={market_condition.mood})")
        return None
    else:
        LOGGER.info(f"✅ {symbol}: {reason}")
    
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
        
        # 🎯 Smart RR Validation (LEGACY CODE - NOT USED, but kept for consistency)
        rr_check = rr_from_levels(prop["entry"], prop["sl"], prop["tp1"])
        
        if rr_check is None:
            return None
        
        # NOTE: This code is unreachable (early return at line 983)
        # If re-enabled, use Smart RR Validation with AI consensus
        consensus_data = ctx.get("_consensus_result")
        min_rr = market_condition.min_rr_threshold
        
        is_valid, reason = validate_rr_smart(
            rr_ratio=rr_check,
            min_rr=min_rr,
            consensus_result=consensus_data,
            symbol=symbol
        )
        
        if not is_valid:
            LOGGER.info(f"🚫 {symbol}: {reason} (LEGACY PATH)")
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

def _calc_grid_budget(symbol: str, ctx: Dict[str, Any]) -> float:
    """
    🎯 GRID-specific budget calculator with $150 minimum floor.
    
    Uses get_grid_budget_usdt to ensure sufficient budget for multi-level GRID trades.
    Each level needs ~$25 budget → $125 notional per level ≥ $100 Binance minimum.
    """
    price = _maybe_float(ctx, "price") or _maybe_float(ctx.get("filters", {}), "price") or None
    atr   = _maybe_float(ctx, "atr", "atr14", "atr_abs") or _maybe_float(ctx.get("filters", {}), "atr", "atr14") or None
    quality = _quality_from_ctx(ctx)
    try:
        from utils.budget import get_grid_budget_usdt
        b = float(get_grid_budget_usdt(symbol=symbol, quality=quality, atr=atr, price=price))
        if b > 0:
            return b
    except Exception as e:
        LOGGER.debug("grid budget failed, fallback to $150: %s", e)
    return 150.0  # GRID minimum budget

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

    # 🎯 GET STRATEGY CONFIG: Already selected in _ai_consensus_suggest_v2!
    # Context now contains _market_condition AND strategy was already selected
    # We just need to extract thresholds from context (set by _ai_consensus_suggest_v2)
    market_condition = ctx.get("_market_condition")
    
    # Get thresholds from market_condition (set by Market Intelligence)
    min_rr = market_condition.min_rr_threshold if market_condition else 1.5
    success_req = max(success_floor, 50.0)  # Default 50%, will be overridden by tier logic
    
    LOGGER.info(
        f"🎯 {symbol}: Using Market Intelligence thresholds → "
        f"MinRR={min_rr:.2f}, MinSuccess={success_req:.1f}%"
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
    
    # 🎯 MULTI-TF GRID SIDE SELECTION: Use 1H+4H trend (not 15M EMA)
    flags = dict(flags)  # Make copy to avoid mutating original
    
    # Extract multi-TF trend analysis from context (set by handle_symbol)
    tf_trend = ctx.get("tf_trend", "NEUTRAL")
    tf_alignment = ctx.get("tf_alignment", "WEAK")
    tf_confidence = ctx.get("tf_confidence", 0.0)
    multi_tf_data = ctx.get("multi_tf", {})
    
    # Determine GRID bias from multi-TF trend (4H=50%, 1H=30%, 15M=20%)
    # LONG if 1H+4H both bullish, SHORT if both bearish, NEUTRAL if conflicting
    grid_bias = tf_trend  # Will be "LONG", "SHORT", or "NEUTRAL"
    
    # Check if we have valid multi-TF data
    if multi_tf_data and len(multi_tf_data) >= 2:
        # Analyze 1H and 4H specifically for GRID direction
        tf_1h = multi_tf_data.get("1h", {})
        tf_4h = multi_tf_data.get("4h", {})
        
        # GRID criteria: Both 1H and 4H must agree (price > EMA20 and positive MACD)
        h1_bullish = False
        h4_bullish = False
        h1_bearish = False
        h4_bearish = False
        
        if tf_1h:
            price_1h = tf_1h.get("close", 0)
            ema20_1h = tf_1h.get("ema_20", 0)
            macd_1h = tf_1h.get("macd", 0)
            h1_bullish = price_1h > ema20_1h and macd_1h > 0
            h1_bearish = price_1h < ema20_1h and macd_1h < 0
        
        if tf_4h:
            price_4h = tf_4h.get("close", 0)
            ema20_4h = tf_4h.get("ema_20", 0)
            macd_4h = tf_4h.get("macd", 0)
            h4_bullish = price_4h > ema20_4h and macd_4h > 0
            h4_bearish = price_4h < ema20_4h and macd_4h < 0
        
        # GRID Side Logic (strict criteria - both TFs must agree)
        if h1_bullish and h4_bullish:
            grid_bias = "LONG"
            LOGGER.info(f"✅ [{symbol}] GRID LONG: 1H+4H both bullish (price>EMA20, MACD>0)")
        elif h1_bearish and h4_bearish:
            grid_bias = "SHORT"
            LOGGER.info(f"✅ [{symbol}] GRID SHORT: 1H+4H both bearish (price<EMA20, MACD<0)")
        else:
            grid_bias = "NEUTRAL"
            LOGGER.info(
                f"⚠️ [{symbol}] GRID NEUTRAL: 1H+4H conflicting "
                f"(1H={'bullish' if h1_bullish else 'bearish'}, "
                f"4H={'bullish' if h4_bullish else 'bearish'}) - skipping GRID"
            )
        
        # Override flags with multi-TF decision
        flags["grid_bias"] = grid_bias
        flags["ema_bullish"] = (grid_bias == "LONG")
        flags["ema_bearish"] = (grid_bias == "SHORT")
    else:
        # Fallback to single-TF if multi-TF unavailable (maintain backward compatibility)
        LOGGER.warning(f"⚠️ [{symbol}] Multi-TF data unavailable, using 15M EMA fallback")
        
        ema_20 = ctx.get("ema_20") or ctx.get("ema21")
        ema_50 = ctx.get("ema_50") or ctx.get("ema50")
        
        # Fetch real indicators if missing
        if not (ema_20 and ema_50):
            try:
                indicators = await _fetch_real_indicators(symbol, interval=DEFAULT_INTERVAL)
                ema_20 = indicators.get("ema_20")
                ema_50 = indicators.get("ema_50")
                ctx.update(indicators)
            except Exception as e:
                LOGGER.debug(f"Failed to fetch real indicators for {symbol}: {e}")
        
        if ema_20 and ema_50:
            flags["ema_bullish"] = ema_20 > ema_50
            flags["ema_bearish"] = ema_20 < ema_50
            grid_bias = "LONG" if ema_20 > ema_50 else "SHORT"
        else:
            grid_bias = "NEUTRAL"
    
    # Skip GRID if trend is NEUTRAL (conflicting timeframes)
    if grid_bias == "NEUTRAL":
        LOGGER.info(f"propose_grid SKIPPED {symbol}: NEUTRAL multi-TF trend (no clear direction)")
        return None
    
    plan = build_grid_plan(symbol=symbol, price=price, flags=flags, budget_usd=_calc_grid_budget(symbol, ctx))
    if not plan:
        LOGGER.info(f"propose_grid REJECTED {symbol}: build_grid_plan returned None (no range)")
        return None
    
    # 🎯 GRID Side Selection - Log multi-TF decision
    grid_side = plan.get("grid_side", grid_bias)
    LOGGER.info(
        f"🎯 GRID Side Selection [{symbol}]: {grid_side} | "
        f"Multi-TF: {tf_trend} (Alignment={tf_alignment}, Confidence={tf_confidence:.1f}%) | "
        f"Decision: {'1H+4H both bullish' if grid_bias == 'LONG' else '1H+4H both bearish' if grid_bias == 'SHORT' else 'conflicting'}"
    )

    # 💰 DYNAMIC SIZING ENGINE: Calculate exact leverage and budget for GRID
    from utils.dynamic_sizing import get_dynamic_sizing_engine
    from utils.binance_client import futures_balance
    
    # Get account equity
    try:
        bals = futures_balance() or []
        usdt_bal = next((b for b in bals if b.get("asset") == "USDT"), {})
        account_equity = float(usdt_bal.get("balance", 0.0))
    except Exception:
        account_equity = 100.0  # Fallback
    
    # Get quality score from context
    quality_score = _quality_from_ctx(ctx) or 6.0  # GRID minimum quality
    volatility = (ctx.get("filters") or {}).get("vol_regime", "medium") or "medium"
    market_condition = ctx.get("_market_condition")
    
    # Calculate dynamic sizing
    dynamic_sizing_engine = get_dynamic_sizing_engine()
    sizing = dynamic_sizing_engine.calculate_position(
        quality_score=quality_score,
        risk_reward=1.5,  # GRID typically has lower RR but more frequent fills
        ai_confidence=70.0,  # GRID is mechanical, not AI-driven
        volatility=volatility,
        account_equity=account_equity,
        market_regime=market_condition.regime if market_condition else "unknown",
        market_mood=market_condition.mood if market_condition else "neutral"
    )
    
    # 🎯 FIX: Use GRID-specific budget from plan (calculated by _calc_grid_budget with $50 minimum)
    # Don't use sizing.size_usd which comes from generic Dynamic Sizing Engine
    leverage = sizing.leverage
    budget = plan["budget_usd"]  # ← Budget from _calc_grid_budget ($50-150)
    notional = budget * leverage  # ← Recalculate notional from GRID budget
    
    LOGGER.info(
        f"💰 GRID Dynamic Sizing: {symbol} → "
        f"Leverage={leverage}x, Budget=${budget:.2f} (before leverage), Position=${notional:.2f}"
    )
    
    # נזילות לנוטיונל
    lg = liquidity_gate_safe(symbol, plan["grid_side"], notional_usd=notional)
    if not (lg.get("ok") if isinstance(lg, dict) else lg):
        LOGGER.info(f"propose_grid REJECTED {symbol}: liquidity_gate failed (notional=${notional})")
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
        "leverage": leverage,  # 🔧 FIX: Dynamic leverage (1-35x)
        "budget_usd": float(budget),  # 🔧 FIX: Budget BEFORE leverage ($25-150)
        "notional_usd": float(notional),  # Position size AFTER leverage
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
        
        # 🎯 MetaBrain v9.1: Balance-Tiered Risk Profiles
        risk_profile_mgr = get_risk_profile_manager()
        risk_profile = risk_profile_mgr.get_profile(account_equity)
        max_leverage_by_balance = risk_profile.max_leverage
        
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
        
        # 🛡️ Apply risk profile leverage cap
        leverage = min(sizing.leverage, max_leverage_by_balance)
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
            f"Leverage={leverage}x (cap={max_leverage_by_balance}x by {risk_profile.name}), "
            f"Budget=${dynamic_budget:.2f}, Position=${notional:.2f}"
        )
        
        # 🎯 MetaBrain v9.1: Multi-Target TP System (100% Dynamic)
        multi_tp_engine = get_multi_target_tp()
        atr_pct = ctx.get("atr_percent", 0.02)  # ATR as percentage
        regime = market_condition.regime if market_condition else "choppy"
        
        # Get win rate from performance tracker (if available)
        win_rate = None
        try:
            perf_tracker = get_performance_tracker()
            symbol_stats = perf_tracker.get_symbol_stats(symbol)
            if symbol_stats and symbol_stats.get("total_trades", 0) > 3:
                win_rate = symbol_stats.get("win_rate", 0.0) / 100.0  # Convert % to 0.0-1.0
        except Exception:
            pass
        
        tp_config = multi_tp_engine.calculate_tp_levels(
            entry_price=float(levels["entry"]),
            stop_loss=float(levels["sl"]),
            strategy="mean_reversion",
            volatility=float(atr_pct),
            regime=regime,
            side=levels["side"],
            win_rate=win_rate  # ✅ DYNAMIC WIN RATE
        )
        
        # Extract TP levels and exit percentages from config
        tp1 = tp_config["targets"][0]["price"]
        tp2 = tp_config["targets"][1]["price"]
        tp3 = tp_config["targets"][2]["price"]
        tp1_pct = tp_config["targets"][0]["exit_percent"]
        tp2_pct = tp_config["targets"][1]["exit_percent"]
        tp3_pct = tp_config["targets"][2]["exit_percent"]
        
        # Log TP allocation with monitoring
        from utils.tp_performance_monitor import get_tp_performance_monitor
        tp_monitor = get_tp_performance_monitor()
        trade_id = f"mr{int(time.time())}{random.randint(100,999)}"
        tp_monitor.log_tp_allocation(
            symbol=symbol,
            strategy="mean_reversion",
            regime=regime,
            volatility=atr_pct,
            tp1_percent=tp1_pct,
            tp2_percent=tp2_pct,
            tp3_percent=tp3_pct,
            trade_id=trade_id
        )
        
        LOGGER.info(
            f"📊 Multi-Target TP: {symbol} → "
            f"TP1={tp1:.4f} ({tp1_pct*100:.0f}%), "
            f"TP2={tp2:.4f} ({tp2_pct*100:.0f}%), "
            f"TP3={tp3:.4f} ({tp3_pct*100:.0f}%), Trailing@TP1"
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
            "tp1": float(tp1),
            "tp2": float(tp2),
            "tp3": float(tp3),
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
    topk = POOL_PER_CYCLE  # 🚀 Always scan 50 symbols per cycle (ignore hours_profile topk)
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
        min_budget = float(os.getenv("BUDGET_MIN_USDT", "25.0"))  # ⬆️ Raised from $10 to $25
        safety_buffer = min_budget * 1.0  # $25 minimum for realistic trades
        if available < safety_buffer:
            LOGGER.warning(
                f"⏸️ ON DEMAND MODE: Insufficient margin (${available:.2f} < ${safety_buffer:.2f}). "
                f"Skipping scan cycle to save resources. "
                f"Fast polling enabled - will resume when margin freed."
            )
            return False  # 🔄 Signal fast polling mode (10-15s)
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
    
    # 🛡️ QUALITY FILTERS: Remove low-quality symbols BEFORE analysis
    # Filter 1: Symbol Blacklist (problematic symbols with poor liquidity/data)
    SYMBOL_BLACKLIST = {"1000WHYUSDT", "AGTUSDT", "AKEUSDT", "1000SATSUSDT", "BONKUSDT"}  # Low-quality meme coins
    pool_syms_filtered = []
    blacklisted_count = 0
    
    for sym in pool_syms:
        # Blacklist check
        if sym in SYMBOL_BLACKLIST:
            LOGGER.debug(f"🚫 Blacklist: {sym} - low-quality/unreliable symbol")
            blacklisted_count += 1
            continue
        
        pool_syms_filtered.append(sym)
    
    if blacklisted_count > 0:
        LOGGER.info(f"🛡️ Quality Filter: Removed {blacklisted_count} blacklisted symbols")
    
    pool_syms = pool_syms_filtered
    
    # 🎯 Filter 2: TOP 50 Pre-Filter (reduce wasted AI calls on symbols that will be blocked)
    try:
        from utils.redis_client import get_redis
        redis_client = get_redis()
        top50_filtered_count = 0
        
        if redis_client:
            import json
            top50_data = redis_client.get("top50:approved_list")
            if top50_data:
                top50_list = json.loads(top50_data)
                if top50_list:
                    pool_syms_top50 = []
                    for sym in pool_syms:
                        if sym.upper() in [s.upper() for s in top50_list]:
                            pool_syms_top50.append(sym)
                        else:
                            top50_filtered_count += 1
                    
                    # Use TOP 50 filtered pool if we got at least 10 symbols, else fail-open
                    if len(pool_syms_top50) >= 10:
                        pool_syms = pool_syms_top50
                        LOGGER.info(f"🎯 TOP 50 Pre-Filter: Kept {len(pool_syms)} symbols, removed {top50_filtered_count} off-list")
                    else:
                        LOGGER.warning(f"⚠️ TOP 50 Pre-Filter: Only {len(pool_syms_top50)} symbols match, keeping full pool (fail-open)")
                else:
                    LOGGER.warning("⚠️ TOP 50 list EMPTY - skipping pre-filter (fail-open)")
            else:
                LOGGER.warning("⚠️ TOP 50 list NOT FOUND in Redis - skipping pre-filter (fail-open)")
    except Exception as e:
        LOGGER.warning(f"TOP 50 Pre-Filter failed: {e} - proceeding with full pool (fail-open)")
    
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
        
        # 📊 CALCULATE ENHANCED QUALITY SCORE (MI + Position Score) - always run for telemetry
        symbol = payload.get("symbol", "")
        if ttype == "GRID":
            LOGGER.info(f"✅ Smart Filter BYPASSED for GRID trade {symbol} (range-based strategy)")
            # 🔧 ENHANCED: Calculate quality from BOTH Market Intelligence AND Position Scoring
            try:
                # Ensure ctx is not None (type guard for LSP)
                if not ctx:
                    ctx = {}
                
                from utils.market_intelligence import get_market_intelligence
                from utils.position_scorer import get_position_scorer
                
                mi_engine = get_market_intelligence()
                position_scorer = get_position_scorer()
                
                # Calculate MI quality (technical indicators)
                mi_quality = mi_engine.calculate_quality_score(ctx, strategy="grid")
                mi_quality = max(6.0, min(mi_quality if mi_quality and mi_quality > 0 else 6.0, 10.0))
                
                # Calculate Position Score (multi-factor quality)
                # Extract risk/reward from payload if available
                entry = payload.get("entry_price", 0)
                sl = payload.get("stop_loss", 0)
                tp = payload.get("take_profit", 0)
                rr_ratio = abs((tp - entry) / (entry - sl)) if entry and sl and tp and entry != sl else 2.0
                
                position_score = position_scorer.calculate_position_score(
                    symbol=symbol,
                    strategy="grid",
                    context=ctx,
                    risk_reward=rr_ratio
                )
                
                # Weighted average: 60% MI + 40% Position Score
                # This gives technical analysis slight edge while incorporating multi-factor quality
                final_quality = (mi_quality * 0.60) + (position_score * 0.40)
                
                # Clamp to 6.0-10.0 range for safety
                payload["quality_score"] = max(6.0, min(final_quality, 10.0))
                
                LOGGER.info(
                    f"📊 GRID quality for {symbol}: {payload['quality_score']:.1f}/10 "
                    f"(MI={mi_quality:.1f}, Position={position_score:.1f}, weighted avg)"
                )
            except Exception as e:
                LOGGER.warning(f"⚠️ Failed to calculate enhanced quality for GRID {symbol}: {e}, using default 6.0")
                payload["quality_score"] = 6.0  # Safe fallback
        
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
            min_budget = float(os.getenv("BUDGET_MIN_USDT", "25.0"))  # ⬆️ Raised from $10 to $25
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
        # ⚠️ BYPASS for GRID + MEAN_REVERSION: Quality score already calculated/approved by Market Intelligence
        if ttype not in ["GRID", "MEAN_REVERSION"]:
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
            
            # Map trade type to strategy type for AI Consensus
            if ttype == "GRID":
                strategy_type = "grid"
            elif ttype == "MEAN_REVERSION":
                strategy_type = "mean_reversion"
            elif ttype == "FUTURES":
                strategy_type = "trend_following"
            else:
                strategy_type = payload.get("strategy_type", "mean_reversion")
            
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
            
            LOGGER.info(f"🧠 Requesting consensus from 3 AI Brains for {symbol} ({ttype})...")
            
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
            
            # 🛡️ CRITICAL SAFETY CHECK: Enforce MIN_QUALITY floor (regime-aware: 4.0 default)
            MIN_QUALITY_FLOOR = 4.0
            final_score = consensus_result["final_score"]
            
            if final_score < MIN_QUALITY_FLOOR:
                LOGGER.warning(
                    f"🚫 QUALITY FLOOR VIOLATION: {symbol} score={final_score:.1f} < {MIN_QUALITY_FLOOR:.1f} "
                    f"(votes={consensus_result['approve_count']}/3) - REJECTED for safety"
                )
                return
            
            # Update payload with consensus scores
            payload["consensus_score"] = consensus_result["final_score"]
            payload["consensus_votes"] = f"{consensus_result['approve_count']}/3"
            
            LOGGER.info(f"✅ APPROVED by AI consensus: {symbol} ({ttype}) - {consensus_result['approve_count']}/3 votes, score={final_score:.1f}/10")
            
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
            # 🎯 GRID trades: Use minimal TTLs to avoid blocking reoccurring proposals
            is_grid = (ttype == "GRID")
            cooldown_ttl = 0 if is_grid else cooldown_sec  # GRID: no cooldown, others: 60s
            dedup_ttl = 300 if is_grid else int(float(os.getenv("DEDUP_TTL_SEC","86400")))  # GRID: 5min, others: 24h
            
            # Cooldown per (symbol,type) - skip if TTL=0
            if cooldown_ttl > 0 and not _pass_cooldown_dyn(payload["symbol"], ttype, cooldown_ttl):
                LOGGER.info(f"⏳ Cooldown active: {payload['symbol']} {ttype} (blocked for {cooldown_ttl}s)")
                return
            
            # 🔍 Dedup check - CHECK ONLY (don't write yet)
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
            k = _dedup_key(h)
            if RED and RED.get(k):
                LOGGER.info(f"🔁 Duplicate proposal blocked: {payload['symbol']} {ttype} (TTL={dedup_ttl}s)")
                return
            
            # 🚀 Emit to ExecutionBot
            ok = await _emit(payload)
            
            # ✅ Only save dedup AFTER successful emit (prevents poisoned keys)
            if ok and RED:
                RED.setex(k, dedup_ttl, "1")
                LOGGER.info(f"✅ Dedup saved after successful emit: {payload['symbol']} {ttype} (TTL={dedup_ttl}s)")
        finally:
            if not ok:
                # החזרה של הטוקן אם נכשלנו בכל זאת
                async with accepted_lock:
                    accepted = max(0, accepted - 1)

    async def handle_symbol(sym: str):
        ctx = ctx_map.get(sym) or {}
        success_floor = SUCCESS_PCT_MIN
        
        # 🎯 MULTI-TIMEFRAME ANALYSIS: Fetch 15M + 1H + 4H data
        try:
            LOGGER.info(f"🔄 [{sym}] Building multi-TF snapshot (15M+1H+4H)...")
            multi_tf_data = await _build_multi_tf_snapshot(sym)
            
            if multi_tf_data and len(multi_tf_data) >= 2:
                # Store in context for downstream use
                ctx["multi_tf"] = multi_tf_data
                
                # Analyze weighted multi-TF trend
                tf_analysis = analyze_multi_tf_weighted(multi_tf_data)
                ctx["tf_trend"] = tf_analysis.trend_direction
                ctx["tf_alignment"] = tf_analysis.alignment_status
                ctx["tf_confidence"] = tf_analysis.weighted_confidence
                
                LOGGER.info(
                    f"✅ [{sym}] Multi-TF Analysis: "
                    f"Trend={tf_analysis.trend_direction}, "
                    f"Alignment={tf_analysis.alignment_status}, "
                    f"Confidence={tf_analysis.weighted_confidence:.1f}%, "
                    f"Dominant={tf_analysis.dominant_timeframe.upper()}"
                )
                
                # Store TF snapshots in database
                try:
                    for interval, indicators in multi_tf_data.items():
                        insert_tf_snapshot({
                            "symbol": sym,
                            "interval": interval,
                            "timestamp": time.time(),
                            "indicators": indicators,
                            "alignment_status": tf_analysis.alignment_status
                        })
                except Exception as e:
                    LOGGER.debug(f"Failed to save TF snapshot: {e}")
            else:
                LOGGER.warning(
                    f"⚠️ [{sym}] Multi-TF snapshot incomplete "
                    f"({len(multi_tf_data)}/3 timeframes) - proceeding with single TF"
                )
        except Exception as e:
            LOGGER.warning(f"⚠️ [{sym}] Multi-TF analysis failed: {e}, proceeding with single TF")
        
        # 🎯 MARKET INTELLIGENCE: Analyze market conditions (no AI call yet!)
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
            
            # 📝 STORE market_condition in ctx for downstream propose_* functions
            # This prevents redundant AI calls - _ai_consensus_suggest_v2 will use this!
            ctx["_market_condition"] = market_condition
            
            # 🚀 ROUTE TO APPROPRIATE STRATEGY based on market_intelligence recommendation
            # (No select_strategy call here - that happens ONCE in _ai_consensus_suggest_v2!)
            recommended = market_condition.recommended_strategy
            
            if recommended == "grid" and SUGGEST_GRID:
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
                    LOGGER.exception(f"propose_grid ERROR {sym}: {e}")  # CHANGED: Use exception() for full traceback
                    # Fallback to FUTURES on error
                    if SUGGEST_FUTURES:
                        try:
                            p = await propose_futures(sym, ctx, success_floor)
                            await maybe_emit("FUTURES", p, ctx)
                        except Exception as e2:
                            LOGGER.exception(f"propose_futures fallback error {sym}: {e2}")
            
            elif recommended == "mean_reversion":
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
            
            elif recommended == "wait":
                # WAIT Mode - very selective
                LOGGER.info(f"⏸️ {sym}: WAIT mode - market uncertain, skipping for now")
                # Still try futures but with very high thresholds (handled internally by AI)
                if SUGGEST_FUTURES:
                    try:
                        p = await propose_futures(sym, ctx, success_floor)
                        await maybe_emit("FUTURES", p, ctx)
                    except Exception as e:
                        LOGGER.exception(f"propose_futures error {sym}: {e}")
            
            else:
                # FUTURES strategies (futures_long, futures_short, or any other)
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
    return True  # ✅ Successful scan completed

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
                cycle_result = await process_cycle()  # 🔄 Get return value
                cycle_duration = time.time() - cycle_start
                
                # 🔄 ON DEMAND MODE: Fast polling when margin insufficient
                # If process_cycle() returned False (skipped scan), use 10s polling
                # If returned True or None (completed scan), use normal interval
                if cycle_result is False:
                    # ⚡ FAST POLLING: Check every 10 seconds for freed margin
                    fast_poll_interval = 10
                    LOGGER.info(
                        f"⏸️ ON DEMAND: Next margin check in {fast_poll_interval}s "
                        f"(fast polling until margin available)"
                    )
                    await asyncio.sleep(fast_poll_interval)
                    continue  # Skip cost logging when no scan occurred
                
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
















