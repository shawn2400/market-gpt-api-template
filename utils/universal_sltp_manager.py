# utils/universal_sltp_manager.py
"""
🎯 Universal SL/TP Protection Manager
Works for ALL trade types: GRID, MARKET, HYBRID, Mean Reversion, Breakout, Dip Buying

Architecture:
1. Save metadata with clientOrderId (not orderId - orderId comes AFTER order placement)
2. Detect fills via Binance API (not open_orders)
3. Attach SL/TP immediately when fill detected
4. Works for all strategies

Key Innovation: clientOrderId-based tracking = 100% reliable!
"""
from __future__ import annotations
import json
import logging
import time
from typing import Dict, Any, Optional, List

logger = logging.getLogger("algogpt.universal_sltp")

# Redis TTL for metadata (24 hours = plenty of time for order to fill)
METADATA_TTL_SECONDS = 86400

def save_order_metadata(
    *,
    client_order_id: str,
    symbol: str,
    side: str,  # LONG/SHORT
    entry_price: float,
    sl_price: float,
    tp_price: float,
    quantity: float,
    leverage: int,
    trade_type: str,  # GRID, MARKET, HYBRID, etc.
    redis_conn=None
) -> bool:
    """
    💾 Save SL/TP metadata for ANY trade type.
    
    Uses clientOrderId as key - this is set BEFORE order placement,
    so we can retrieve it reliably when the fill arrives.
    
    Args:
        client_order_id: Unique client order ID (from build_client_order_id)
        symbol: Trading pair
        side: LONG or SHORT
        entry_price: Expected entry price
        sl_price: Stop loss price
        tp_price: Take profit price
        quantity: Order quantity
        leverage: Position leverage
        trade_type: GRID, MARKET, HYBRID, etc.
        redis_conn: Redis connection (optional, will create if None)
    
    Returns:
        True if saved successfully, False otherwise
    """
    try:
        if redis_conn is None:
            from utils.redis_client import redis_client
            redis_conn = redis_client
        
        if not redis_conn:
            logger.warning(f"⚠️ Redis unavailable - cannot save metadata for {client_order_id}")
            return False
        
        metadata = {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "quantity": quantity,
            "leverage": leverage,
            "trade_type": trade_type,
            "created_at": time.time(),
        }
        
        # Store with clientOrderId as key
        redis_key = f"sltp:meta:{client_order_id}"
        redis_conn.setex(redis_key, METADATA_TTL_SECONDS, json.dumps(metadata))
        
        logger.info(f"💾 Metadata saved: {redis_key} | {trade_type} {symbol} {side} @ {entry_price:.6f}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to save metadata for {client_order_id}: {e}", exc_info=True)
        return False


def get_order_metadata(client_order_id: str, redis_conn=None) -> Optional[Dict[str, Any]]:
    """
    📖 Retrieve SL/TP metadata by clientOrderId.
    
    Args:
        client_order_id: Client order ID to lookup
        redis_conn: Redis connection (optional)
    
    Returns:
        Metadata dict or None if not found
    """
    try:
        if redis_conn is None:
            from utils.redis_client import redis_client
            redis_conn = redis_client
        
        if not redis_conn:
            return None
        
        redis_key = f"sltp:meta:{client_order_id}"
        metadata_json = redis_conn.get(redis_key)
        
        if not metadata_json:
            logger.debug(f"🔍 No metadata found for {client_order_id}")
            return None
        
        if isinstance(metadata_json, bytes):
            metadata_json = metadata_json.decode('utf-8')
        
        metadata = json.loads(metadata_json)
        logger.debug(f"📖 Metadata retrieved for {client_order_id}: {metadata.get('trade_type')} {metadata.get('symbol')}")
        return metadata
        
    except Exception as e:
        logger.error(f"❌ Failed to retrieve metadata for {client_order_id}: {e}")
        return None


def delete_order_metadata(client_order_id: str, redis_conn=None) -> bool:
    """
    🗑️ Delete metadata after SL/TP successfully attached.
    Prevents stale metadata from causing issues.
    """
    try:
        if redis_conn is None:
            from utils.redis_client import redis_client
            redis_conn = redis_client
        
        if not redis_conn:
            return False
        
        redis_key = f"sltp:meta:{client_order_id}"
        deleted = redis_conn.delete(redis_key)
        
        if deleted:
            logger.debug(f"🗑️ Metadata deleted: {redis_key}")
        return bool(deleted)
        
    except Exception as e:
        logger.error(f"❌ Failed to delete metadata for {client_order_id}: {e}")
        return False


async def attach_sltp_protection(
    *,
    symbol: str,
    side: str,  # LONG/SHORT
    sl_price: float,
    tp_price: float,
    position_side: Optional[str] = None
) -> Dict[str, Any]:
    """
    🛡️ Attach SL/TP protection to an open position.
    
    DEPRECATED: Use attach_multi_target_protection() for Multi-Target TP (TP1/TP2/TP3)
    
    Places STOP_MARKET + TAKE_PROFIT_MARKET orders.
    Works for all trade types!
    
    Returns:
        {"ok": bool, "sl_order": dict, "tp_order": dict, "errors": list}
    """
    result = {
        "ok": False,
        "sl_order": None,
        "tp_order": None,
        "errors": []
    }
    
    try:
        from utils.binance_client import client
        from utils.order_ids import build_client_order_id
        
        # Determine order sides
        sl_side = "SELL" if side == "LONG" else "BUY"
        tp_side = "SELL" if side == "LONG" else "BUY"
        
        # Place SL order
        try:
            logger.info(f"📤 Placing SL: {symbol} {sl_side} @ {sl_price:.6f} (STOP_MARKET)")
            
            sl_order = client.futures_create_order(
                symbol=symbol,
                side=sl_side,
                type="STOP_MARKET",
                stopPrice=str(sl_price),
                closePosition=True,
                newClientOrderId=build_client_order_id(symbol, sl_side, role="SL")
            )
            result["sl_order"] = sl_order
            logger.info(f"✅ SL placed: {symbol} @ {sl_price:.6f} | Order ID: {sl_order.get('orderId')}")
            
        except Exception as sl_err:
            error_msg = f"SL placement failed: {sl_err}"
            result["errors"].append(error_msg)
            logger.error(f"❌ {error_msg}", exc_info=True)
        
        # Place TP order
        try:
            logger.info(f"📤 Placing TP: {symbol} {tp_side} @ {tp_price:.6f} (TAKE_PROFIT_MARKET)")
            
            tp_order = client.futures_create_order(
                symbol=symbol,
                side=tp_side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=str(tp_price),
                closePosition=True,
                newClientOrderId=build_client_order_id(symbol, tp_side, role="TP")
            )
            result["tp_order"] = tp_order
            logger.info(f"✅ TP placed: {symbol} @ {tp_price:.6f} | Order ID: {tp_order.get('orderId')}")
            
        except Exception as tp_err:
            error_msg = f"TP placement failed: {tp_err}"
            result["errors"].append(error_msg)
            logger.error(f"❌ {error_msg}", exc_info=True)
        
        # Check if both succeeded
        result["ok"] = (result["sl_order"] is not None and result["tp_order"] is not None)
        
        if result["ok"]:
            logger.info(f"🛡️ Protection complete for {symbol}: SL @ {sl_price:.6f}, TP @ {tp_price:.6f}")
        else:
            logger.warning(f"⚠️ Partial protection for {symbol}: {len(result['errors'])} errors")
        
        return result
        
    except Exception as e:
        error_msg = f"attach_sltp_protection failed: {e}"
        result["errors"].append(error_msg)
        logger.error(f"❌ {error_msg}", exc_info=True)
        return result


async def attach_multi_target_protection(
    *,
    symbol: str,
    side: str,  # LONG/SHORT
    entry_price: float,
    sl_price: float,
    total_quantity: float,
    leverage: int = 10,
    strategy: str = "momentum",
    volatility: Optional[float] = None,
    regime: str = "choppy",
    win_rate: Optional[float] = None,
    position_side: Optional[str] = None
) -> Dict[str, Any]:
    """
    🎯 Attach Multi-Target TP Protection (TP1/TP2/TP3) + SL to an open position.
    
    This is the NEW STANDARD for all positions - replaces single TP with 3-level targets.
    
    Features:
    - 3 TP targets with DYNAMIC exit percentages (adapts to volatility, regime, strategy, win rate)
    - Volatility-adjusted RR ratios
    - Regime-aware TP placement
    - Trailing stop activation at TP1
    
    Args:
        symbol: Trading symbol (e.g., 'BTCUSDT')
        side: LONG or SHORT
        entry_price: Entry price
        sl_price: Stop loss price
        total_quantity: Total position quantity
        leverage: Position leverage (default 10)
        strategy: Trading strategy (momentum, breakout, mean_reversion, grid, etc.)
        volatility: ATR percentage (0.0-1.0), calculated if None
        regime: Market regime (bull, bear, choppy, volatile)
        win_rate: Historical win rate (0.0-1.0), None if unknown
        position_side: Binance position side (LONG/SHORT/BOTH)
    
    Returns:
        {
            "ok": bool,
            "sl_order": dict,
            "tp_orders": list[dict],  # TP1, TP2, TP3
            "tp_config": dict,  # Full TP configuration from MultiTargetTP
            "errors": list
        }
    """
    result = {
        "ok": False,
        "sl_order": None,
        "tp_orders": [],
        "tp_config": None,
        "errors": []
    }
    
    try:
        from utils.binance_client import client, get_symbol_filters
        from utils.order_ids import build_client_order_id
        from utils.multi_target_tp import get_multi_target_tp
        
        # Calculate volatility if not provided
        if volatility is None:
            try:
                from utils.get_klines import get_klines
                from utils.indicators import atr as calculate_atr
                import pandas as pd
                
                klines = await get_klines(symbol, interval="15m", limit=24)
                if klines and len(klines) >= 14:
                    df = pd.DataFrame(klines)
                    atr_series = calculate_atr(df, period=14)
                    if not atr_series.empty:
                        atr_value = float(atr_series.iloc[-1])
                        volatility = atr_value / entry_price
                        logger.info(f"📊 {symbol}: Calculated ATR volatility={volatility*100:.2f}%")
            except Exception as atr_err:
                logger.warning(f"⚠️ Failed to calculate ATR, using default 2%: {atr_err}")
                volatility = 0.02  # Default 2%
        
        if volatility is None:
            volatility = 0.02  # Fallback
        
        # Initialize Multi-Target TP calculator
        mt_tp = get_multi_target_tp()
        
        # Calculate TP levels (TP1, TP2, TP3 with dynamic exit percentages)
        tp_config = mt_tp.calculate_tp_levels(
            entry_price=entry_price,
            stop_loss=sl_price,
            strategy=strategy,
            volatility=volatility,
            regime=regime,
            side=side,
            win_rate=win_rate
        )
        
        result["tp_config"] = tp_config
        
        # Log TP configuration
        logger.info(f"📊 {symbol} Multi-Target TP:\n{mt_tp.format_tp_summary(tp_config)}")
        
        # Determine order sides
        sl_side = "SELL" if side == "LONG" else "BUY"
        tp_side = "SELL" if side == "LONG" else "BUY"
        
        # Get symbol filters for precision
        filters = get_symbol_filters(symbol) or {}
        price_precision = filters.get("pricePrecision", 2)
        qty_precision = filters.get("quantityPrecision", 3)
        
        # Place SL order (STOP_MARKET for guaranteed execution)
        try:
            logger.info(f"📤 Placing SL: {symbol} {sl_side} @ {sl_price:.{price_precision}f} (STOP_MARKET)")
            
            sl_order = client.futures_create_order(
                symbol=symbol,
                side=sl_side,
                type="STOP_MARKET",
                stopPrice=f"{sl_price:.{price_precision}f}",
                closePosition=True,
                newClientOrderId=build_client_order_id(symbol, sl_side, role="SL"),
                positionSide=position_side if position_side else None
            )
            result["sl_order"] = sl_order
            logger.info(f"✅ SL placed: {symbol} @ {sl_price:.{price_precision}f} | Order ID: {sl_order.get('orderId')}")
            
        except Exception as sl_err:
            error_msg = f"SL placement failed: {sl_err}"
            result["errors"].append(error_msg)
            logger.error(f"❌ {error_msg}", exc_info=True)
        
        # Place TP orders (TP1, TP2, TP3) - use LIMIT orders for precision
        for i, target in enumerate(tp_config["targets"], start=1):
            try:
                tp_price = target["price"]
                exit_percent = target["exit_percent"]
                tp_quantity = total_quantity * exit_percent
                
                # Round to symbol precision
                tp_quantity_str = f"{tp_quantity:.{qty_precision}f}"
                tp_price_str = f"{tp_price:.{price_precision}f}"
                
                logger.info(
                    f"📤 Placing TP{i}: {symbol} {tp_side} @ {tp_price_str} "
                    f"({exit_percent*100:.0f}% = {tp_quantity_str}) (LIMIT)"
                )
                
                # 🛡️ CRITICAL: Build TP order params
                tp_order_params = {
                    "symbol": symbol,
                    "side": tp_side,
                    "type": "LIMIT",
                    "price": tp_price_str,
                    "quantity": tp_quantity_str,
                    "timeInForce": "GTC",
                    "newClientOrderId": build_client_order_id(symbol, tp_side, role=f"TP{i}")
                }
                
                # Add positionSide only if hedge mode (not BOTH)
                if position_side and position_side != "BOTH":
                    tp_order_params["positionSide"] = position_side
                else:
                    # In One-Way Mode, set reduceOnly=True to prevent increasing position
                    tp_order_params["reduceOnly"] = True
                
                tp_order = client.futures_create_order(**tp_order_params)
                
                result["tp_orders"].append(tp_order)
                logger.info(
                    f"✅ TP{i} placed: {symbol} @ {tp_price_str} "
                    f"({exit_percent*100:.0f}%) | Order ID: {tp_order.get('orderId')}"
                )
                
            except Exception as tp_err:
                error_msg = f"TP{i} placement failed: {tp_err}"
                result["errors"].append(error_msg)
                logger.error(f"❌ {error_msg}", exc_info=True)
        
        # Check success
        result["ok"] = (
            result["sl_order"] is not None and 
            len(result["tp_orders"]) == 3
        )
        
        if result["ok"]:
            logger.info(
                f"🛡️ Multi-Target Protection complete for {symbol}:\n"
                f"   SL @ {sl_price:.{price_precision}f}\n"
                f"   TP1 @ {tp_config['targets'][0]['price']:.{price_precision}f} ({tp_config['targets'][0]['exit_percent']*100:.0f}%)\n"
                f"   TP2 @ {tp_config['targets'][1]['price']:.{price_precision}f} ({tp_config['targets'][1]['exit_percent']*100:.0f}%)\n"
                f"   TP3 @ {tp_config['targets'][2]['price']:.{price_precision}f} ({tp_config['targets'][2]['exit_percent']*100:.0f}%)"
            )
        else:
            logger.warning(f"⚠️ Partial protection for {symbol}: {len(result['errors'])} errors")
        
        return result
        
    except Exception as e:
        error_msg = f"attach_multi_target_protection failed: {e}"
        result["errors"].append(error_msg)
        logger.error(f"❌ {error_msg}", exc_info=True)
        return result
