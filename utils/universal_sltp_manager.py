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
