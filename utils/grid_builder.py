# utils/grid_builder.py
from __future__ import annotations
from typing import Dict, Any, Optional, Tuple
import os

# פרמטרי גריד לפי משטר תנודתיות (ניתנים לשינוי ב־ENV)
GRID_LEVELS_LOW  = int(os.getenv("GRID_LEVELS_LOW",  "8"))
GRID_LEVELS_MID  = int(os.getenv("GRID_LEVELS_MID",  "6"))
GRID_LEVELS_HIGH = int(os.getenv("GRID_LEVELS_HIGH", "4"))

STEP_PCT_LOW  = float(os.getenv("GRID_STEP_PCT_LOW",  "0.50"))  # אחוז בין קווים
STEP_PCT_MID  = float(os.getenv("GRID_STEP_PCT_MID",  "0.80"))
STEP_PCT_HIGH = float(os.getenv("GRID_STEP_PCT_HIGH", "1.20"))

TP_PER_FILL_PCT = float(os.getenv("GRID_TP_PER_FILL_PCT", "0.35"))  # יעד חלקי לכל מילוי
RANGE_MULT      = float(os.getenv("GRID_RANGE_MULT",       "1.05"))  # כדי להרחיב מעט את הטווח מדדית

def _pick_by_vol(vol_regime: str) -> Tuple[int, float]:
    v = (vol_regime or "mid").lower()
    if v.startswith("low"):
        return GRID_LEVELS_LOW, STEP_PCT_LOW
    if v.startswith("high"):
        return GRID_LEVELS_HIGH, STEP_PCT_HIGH
    return GRID_LEVELS_MID, STEP_PCT_MID

def _determine_grid_side(symbol: str, flags: Dict[str, Any]) -> str:
    """
    🎯 Dynamic GRID Side Selection based on market direction.
    
    Rules:
    1. EMA Alignment: bearish (EMA20 < EMA50) → SHORT, bullish → LONG
    2. BTC Correlation: If symbol != BTC, check BTC direction and align
    3. Default: LONG (conservative bias for altcoins in uncertain conditions)
    
    Returns: "LONG" or "SHORT"
    """
    # Get EMA alignment from flags
    ema_bullish = flags.get("ema_bullish", False)
    ema_bearish = flags.get("ema_bearish", False)
    
    # Get BTC direction if available (for altcoin correlation)
    btc_bullish = flags.get("btc_bullish", None)
    btc_bearish = flags.get("btc_bearish", None)
    
    # Decision Logic:
    # 1. If symbol shows clear bearish EMA → SHORT
    if ema_bearish:
        # Double-check with BTC for altcoins (most altcoins follow BTC)
        if symbol != "BTCUSDT" and btc_bullish:
            # Altcoin bearish but BTC bullish → risky, prefer LONG
            return "LONG"
        return "SHORT"
    
    # 2. If symbol shows clear bullish EMA → LONG
    if ema_bullish:
        return "LONG"
    
    # 3. Neutral/uncertain → check BTC direction for altcoins
    if symbol != "BTCUSDT":
        if btc_bearish:
            return "SHORT"
        if btc_bullish:
            return "LONG"
    
    # 4. Default: LONG (conservative)
    return "LONG"

def build_grid_plan(
    *,
    symbol: str,
    price: Optional[float],
    flags: Dict[str, Any],
    budget_usd: float
) -> Optional[Dict[str, Any]]:
    """
    בונה תוכנית גריד דינמית סביב המחיר:
      - מתאים יותר כשאין טרנד ברור / chop (לא יפתח בטרנד חזק).
      - 🎯 Dynamic Side Selection: LONG/SHORT לפי כיוון השוק (BTC correlation + EMA)
    """
    if not price or price <= 0:
        return None

    vol = (flags or {}).get("vol_regime", "mid").lower()
    trending_up = bool((flags or {}).get("trending_up", False))
    trending_dn = bool((flags or {}).get("trending_down", False))
    chop        = bool((flags or {}).get("danger_chop", False))

    # אם יש טרנד חזק — לא נקים גריד (נמנע ממלכודות)
    if trending_up or trending_dn:
        return None
    
    # 🎯 Dynamic GRID Side Selection (LONG/SHORT based on market direction)
    grid_side = _determine_grid_side(symbol, flags)

    levels, step_pct = _pick_by_vol(vol)
    # חישוב טווח סימטרי סביב המחיר
    half_range_pct = (step_pct * (levels - 1)) / 100.0 * RANGE_MULT
    
    # 🎯 CLAMP RANGE TO ±3-6% (volatility-aware, per user spec: "realistic 3-8% deviation")
    # - Low vol: max 3% each side (6% total)
    # - Mid vol: max 4% each side (8% total)
    # - High vol: max 5% each side (10% total, but we cap at 6% per architect)
    max_half_range_map = {
        "low": 0.03,   # 3% each side = 6% total
        "mid": 0.04,   # 4% each side = 8% total  
        "high": 0.05,  # 5% each side = 10% total
    }
    max_half_range = max_half_range_map.get(vol, 0.04)  # Default: 4%
    half_range_pct = min(half_range_pct, max_half_range)
    
    gmin = price * (1.0 - half_range_pct)
    gmax = price * (1.0 + half_range_pct)
    
    # Check minimum range width - LOWERED from 4% to 2% for more opportunities
    range_width_pct = ((gmax - gmin) / price) * 100.0
    min_range_pct = float(os.getenv("GRID_MIN_RANGE_PCT", "2.0"))  # ✅ LOWERED from 4% to 2%
    
    if range_width_pct < min_range_pct:
        # Range too narrow - GRID not profitable
        return None

    return {
        "symbol": symbol.upper(),
        "grid_min": float(gmin),
        "grid_max": float(gmax),
        "grid_levels": int(levels),
        "grid_step_pct": float(step_pct),
        "grid_take_profit_pct": float(TP_PER_FILL_PCT),
        "grid_side": grid_side,  # 🎯 Dynamic LONG/SHORT
        "reason": f"grid {grid_side} by vol={vol}, levels={levels}, step={step_pct:.2f}%, chop={chop}, range={range_width_pct:.1f}%",
        "budget_usd": float(budget_usd),
    }

   
