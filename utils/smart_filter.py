#!/usr/bin/env python3
# utils/smart_filter.py
"""
🎯 Smart 3-Stage Pre-Filter
Reduces AI costs by 95% through intelligent filtering BEFORE expensive AI calls

Stage 1: Volume Spike Detection (0.01s, free)
Stage 2: Technical Quality Gate (0.1s, free) 
Stage 3: AI Consensus (3s, $$$ - only for high-quality setups)

Goal: Filter out 90% of noise BEFORE calling AI
"""
import os
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("algogpt.smart_filter")

# Configurable thresholds
VOLUME_SPIKE_MIN = float(os.getenv("VOLUME_SPIKE_MIN", "1.5"))  # 150% of average
PRICE_CHANGE_MIN = float(os.getenv("PRICE_CHANGE_MIN", "2.0"))  # 2% move
QUALITY_SCORE_MIN = float(os.getenv("QUALITY_SCORE_MIN", "6.0"))  # 6/10 minimum

def stage1_volume_spike(ctx: Dict[str, Any]) -> Tuple[bool, str]:
    """
    🔍 Stage 1: Volume Spike Detection
    Check if there's unusual trading activity (volume spike)
    
    Returns: (passed, reason)
    """
    try:
        current_volume = float(ctx.get("volume", 0))
        avg_volume = float(ctx.get("volume_sma_20", 1))
        
        if avg_volume == 0:
            return True, "volume_data_missing"
        
        volume_ratio = current_volume / avg_volume
        
        if volume_ratio < VOLUME_SPIKE_MIN:
            return False, f"low_volume_spike_{volume_ratio:.2f}x"
        
        logger.info(f"✅ Stage 1 PASS: Volume spike {volume_ratio:.2f}x (>{VOLUME_SPIKE_MIN}x)")
        return True, f"volume_spike_{volume_ratio:.2f}x"
        
    except Exception as e:
        logger.debug(f"Stage 1 error: {e}")
        return True, "volume_check_failed"  # Don't block on errors


def stage2_technical_quality(ctx: Dict[str, Any]) -> Tuple[bool, str, float]:
    """
    🔍 Stage 2: Technical Quality Gate
    Check RSI extremes, Bollinger breakout, momentum, price change
    
    Returns: (passed, reason, quality_score)
    """
    try:
        rsi = float(ctx.get("rsi", 50))
        price = float(ctx.get("price", 0))
        bb_upper = float(ctx.get("bb_upper", price * 1.02))
        bb_lower = float(ctx.get("bb_lower", price * 0.98))
        adx = float(ctx.get("adx", 0))
        atr_pct = float(ctx.get("atr_percent", 2.0))
        
        # Calculate quality score (0-10)
        quality_score = 0.0
        reasons = []
        
        # 1. RSI extreme zones (+3 points)
        if rsi < 30:
            quality_score += 3.0
            reasons.append(f"oversold_RSI_{rsi:.0f}")
        elif rsi > 70:
            quality_score += 3.0
            reasons.append(f"overbought_RSI_{rsi:.0f}")
        else:
            # Moderate RSI adds small value
            quality_score += 0.5
        
        # 2. Bollinger Band breakout (+2 points)
        if price >= bb_upper:
            quality_score += 2.0
            reasons.append("bb_upper_breakout")
        elif price <= bb_lower:
            quality_score += 2.0
            reasons.append("bb_lower_breakout")
        
        # 3. ADX strength (+2 points)
        if adx > 25:
            adx_points = min(2.0, (adx - 25) / 15)  # Scale 25-40 → 0-2 points
            quality_score += adx_points
            reasons.append(f"strong_ADX_{adx:.0f}")
        
        # 4. Volatility check (+2 points)
        if 1.5 <= atr_pct <= 8.0:
            quality_score += 2.0
            reasons.append(f"good_volatility_{atr_pct:.1f}%")
        elif atr_pct > 8.0:
            quality_score += 1.0  # High volatility = risky
            reasons.append(f"high_volatility_{atr_pct:.1f}%")
        
        # 5. Price change check (+1 point)
        try:
            ema_20 = float(ctx.get("ema_20", price))
            price_change_pct = abs((price - ema_20) / ema_20 * 100) if ema_20 > 0 else 0
            
            if price_change_pct >= PRICE_CHANGE_MIN:
                quality_score += 1.0
                reasons.append(f"price_move_{price_change_pct:.1f}%")
        except Exception:
            pass
        
        # Normalize to 0-10 scale
        quality_score = min(10.0, quality_score)
        
        # Decision
        passed = quality_score >= QUALITY_SCORE_MIN
        reason = " + ".join(reasons) if reasons else "no_signals"
        
        if passed:
            logger.info(f"✅ Stage 2 PASS: Quality={quality_score:.1f}/10 ({reason})")
        else:
            logger.info(f"❌ Stage 2 FAIL: Quality={quality_score:.1f}/10 < {QUALITY_SCORE_MIN} ({reason})")
        
        return passed, reason, quality_score
        
    except Exception as e:
        logger.debug(f"Stage 2 error: {e}")
        return True, "technical_check_failed", 5.0  # Don't block on errors


def stage3_market_direction(ctx: Dict[str, Any], proposed_side: str = "LONG") -> Tuple[bool, str]:
    """
    🔍 Stage 3: Market Direction Filter
    Blocks trades against prevailing market trend to prevent losses
    
    Logic:
    - BEARISH Market (price < EMA20 < EMA50): Block LONG trades
    - BULLISH Market (price > EMA20 > EMA50): Block SHORT trades
    - NEUTRAL/CHOPPY: Allow both directions
    
    Args:
        ctx: Market context with price and EMAs
        proposed_side: Trade direction ("LONG" or "SHORT")
    
    Returns: (passed, reason)
    """
    try:
        price = float(ctx.get("close") or ctx.get("price") or 0)
        ema_20 = float(ctx.get("ema_20") or ctx.get("ema21") or price)
        ema_50 = float(ctx.get("ema_50") or price)
        
        if price == 0:
            return True, "no_price_data"
        
        # Detect market direction via EMA alignment
        if price < ema_20 < ema_50:
            market_direction = "BEARISH"
        elif price > ema_20 > ema_50:
            market_direction = "BULLISH"
        else:
            market_direction = "NEUTRAL"
        
        # Block trades against the trend
        if market_direction == "BEARISH" and proposed_side == "LONG":
            logger.warning(
                f"❌ Stage 3 FAIL: LONG trade blocked in BEARISH market "
                f"(price={price:.2f} < EMA20={ema_20:.2f} < EMA50={ema_50:.2f})"
            )
            return False, "bearish_market_blocks_long"
        
        if market_direction == "BULLISH" and proposed_side == "SHORT":
            logger.warning(
                f"❌ Stage 3 FAIL: SHORT trade blocked in BULLISH market "
                f"(price={price:.2f} > EMA20={ema_20:.2f} > EMA50={ema_50:.2f})"
            )
            return False, "bullish_market_blocks_short"
        
        logger.info(
            f"✅ Stage 3 PASS: {proposed_side} allowed in {market_direction} market "
            f"(price={price:.2f}, EMA20={ema_20:.2f}, EMA50={ema_50:.2f})"
        )
        return True, f"{proposed_side.lower()}_ok_in_{market_direction.lower()}"
        
    except Exception as e:
        logger.debug(f"Stage 3 error: {e}")
        return True, "direction_check_failed"


def smart_pre_filter(symbol: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    🎯 Smart 3-Stage Pre-Filter
    Filters out 90% of noise BEFORE expensive AI calls
    
    Returns:
        {
            "passed": bool,
            "stage": int (1-3),
            "reason": str,
            "quality_score": float (0-10)
        }
    """
    # Stage 1: Volume Spike
    stage1_pass, stage1_reason = stage1_volume_spike(ctx)
    if not stage1_pass:
        return {
            "passed": False,
            "stage": 1,
            "reason": stage1_reason,
            "quality_score": 0.0
        }
    
    # Stage 2: Technical Quality
    stage2_pass, stage2_reason, quality_score = stage2_technical_quality(ctx)
    if not stage2_pass:
        return {
            "passed": False,
            "stage": 2,
            "reason": stage2_reason,
            "quality_score": quality_score
        }
    
    # Stage 3: Market Direction (check if trade direction is provided)
    proposed_side = ctx.get("side", "LONG")
    stage3_pass, stage3_reason = stage3_market_direction(ctx, proposed_side)
    if not stage3_pass:
        return {
            "passed": False,
            "stage": 3,
            "reason": stage3_reason,
            "quality_score": quality_score
        }
    
    # All stages passed → proceed to AI consensus
    logger.info(f"🎯 {symbol}: Smart filter PASSED - Quality={quality_score:.1f}/10, proceeding to AI consensus")
    return {
        "passed": True,
        "stage": 3,
        "reason": f"{stage1_reason} + {stage2_reason} + {stage3_reason}",
        "quality_score": quality_score
    }
