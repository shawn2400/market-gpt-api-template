#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Emergency Auto-Protect System
🛡️ Attach SL/TP to any open positions without protection
"""
import asyncio
import logging
import os
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("auto_protect")

async def protect_unprotected_positions() -> Dict[str, Any]:
    """
    🛡️ Scan for unprotected positions and attach SL/TP automatically
    
    Returns:
        Summary of protected positions
    """
    try:
        from utils.binance_client import futures_open_positions_safe, futures_mark_price
        from utils.universal_sltp_manager import attach_multi_target_protection
        
        # Get all open positions
        positions_raw = futures_open_positions_safe() or []
        open_positions = [p for p in positions_raw if float(p.get("positionAmt", 0)) != 0]
        
        if not open_positions:
            logger.info("✅ No open positions")
            return {"ok": True, "protected": 0, "skipped": 0}
        
        protected = 0
        skipped = 0
        
        logger.info(f"🔍 Found {len(open_positions)} open positions - checking protection...")
        
        for pos in open_positions:
            symbol = pos["symbol"]
            position_amt = float(pos.get("positionAmt", 0))
            entry_price = float(pos.get("entryPrice", 0))
            position_side = pos.get("positionSide", "BOTH")
            
            if position_amt == 0 or entry_price <= 0:
                continue
            
            side = "LONG" if position_amt > 0 else "SHORT"
            quantity = abs(position_amt)
            
            try:
                # Check if position has open SL/TP orders
                from utils.binance_client import futures_get_open_orders
                orders = futures_get_open_orders(symbol=symbol) or []
                
                has_sl = any(o.get("type") in ("STOP_MARKET", "STOP") for o in orders)
                has_tp = any(o.get("type") in ("TAKE_PROFIT_MARKET", "LIMIT") and o.get("reduceOnly") for o in orders)
                
                if has_sl and has_tp:
                    logger.debug(f"✅ {symbol} {side} already protected - skipping")
                    skipped += 1
                    continue
                
                # No protection - attach it!
                logger.info(f"🛡️ {symbol} {side} qty={quantity} - UNPROTECTED - attaching SL/TP...")
                
                # Get current price safely
                current_price_val = futures_mark_price(symbol)  # type: ignore
                current_price = float(current_price_val) if current_price_val else entry_price
                atr = current_price * 0.02  # 2% ATR
                sl_price = entry_price - atr if side == "LONG" else entry_price + atr
                
                # Attach protection
                result = await attach_multi_target_protection(
                    symbol=symbol,
                    side=side,
                    entry_price=entry_price,
                    sl_price=sl_price,
                    total_quantity=quantity,
                    leverage=1,
                    strategy="auto_protect_existing",
                    volatility=0.02,
                    regime="unknown",
                    position_side=position_side if position_side != "BOTH" else None
                )
                
                if result.get("ok"):
                    logger.info(f"✅ Protected {symbol} - SL + {len(result.get('tp_orders', []))} TP orders")
                    protected += 1
                else:
                    logger.error(f"❌ Failed to protect {symbol}: {result.get('errors')}")
                    
            except Exception as e:
                logger.error(f"❌ Error processing {symbol}: {e}")
        
        logger.info(f"\n{'='*50}")
        logger.info(f"✅ RESULT: Protected {protected} positions, {skipped} already safe")
        logger.info(f"{'='*50}\n")
        
        return {"ok": True, "protected": protected, "skipped": skipped}
        
    except Exception as e:
        logger.error(f"❌ Auto-protect failed: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}

if __name__ == "__main__":
    asyncio.run(protect_unprotected_positions())
