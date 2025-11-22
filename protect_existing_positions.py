#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protect Existing Positions - Attach TP/SL to open trades
שומר הלאום לטריידים פתוחים
"""
import asyncio
import logging
import os
from typing import Dict, List, Any, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("protect_positions")

async def protect_all_open_positions(dry_run: bool = True) -> Dict[str, Any]:
    """
    🛡️ Attach TP/SL to ALL open positions
    
    Args:
        dry_run: If True, only show what WOULD happen (no actual orders)
    
    Returns:
        Summary of what was protected
    """
    try:
        from utils.binance_client import get_futures_client
        from utils.universal_sltp_manager import attach_multi_target_protection
        from utils.advanced_risk_manager import get_risk_manager
        
        client = get_futures_client()
        if not client:
            logger.error("❌ Binance client unavailable")
            return {"ok": False, "error": "client_unavailable"}
        
        # Get all open positions
        positions = client.futures_position_information()
        open_positions = [p for p in positions if float(p.get("positionAmt", 0)) != 0]
        
        if not open_positions:
            logger.info("✅ No open positions to protect")
            return {"ok": True, "protected": 0, "positions": []}
        
        protected = []
        errors = []
        
        for pos in open_positions:
            symbol = pos["symbol"]
            position_amt = float(pos.get("positionAmt", 0))
            entry_price = float(pos.get("entryPrice", 0))
            position_side = pos.get("positionSide", "BOTH")
            
            if position_amt == 0:
                continue
            
            side = "LONG" if position_amt > 0 else "SHORT"
            quantity = abs(position_amt)
            
            logger.info(f"\n🛡️ Protecting {symbol} {side} qty={quantity:.6f} @ {entry_price:.6f}")
            
            try:
                # Calculate SL using ATR
                from utils.binance_client import get_price
                from utils.sltp import calc_sl_tp_for_symbol
                
                current_price = get_price(symbol) or entry_price
                atr = current_price * 0.02  # Default 2% volatility
                
                sl_price, tp_price = calc_sl_tp_for_symbol(
                    symbol=symbol,
                    entry=entry_price,
                    side=side,
                    atr_pct=0.02,
                    leverage=1.0
                )
                
                if dry_run:
                    logger.info(
                        f"  📋 DRY RUN: Would attach SL={sl_price:.6f}, TP={tp_price:.6f}"
                    )
                    protected.append({
                        "symbol": symbol,
                        "side": side,
                        "quantity": quantity,
                        "entry": entry_price,
                        "sl": sl_price,
                        "tp": tp_price,
                        "dry_run": True
                    })
                else:
                    # Actually attach protection
                    result = await attach_multi_target_protection(
                        symbol=symbol,
                        side=side,
                        entry_price=entry_price,
                        sl_price=sl_price,
                        total_quantity=quantity,
                        leverage=1,
                        strategy="protect_existing",
                        volatility=0.02,
                        regime="unknown",
                        position_side=position_side if position_side != "BOTH" else None
                    )
                    
                    if result.get("ok"):
                        logger.info(f"  ✅ SL={sl_price:.6f}, TP={tp_price:.6f}")
                        protected.append({
                            "symbol": symbol,
                            "side": side,
                            "quantity": quantity,
                            "entry": entry_price,
                            "sl": sl_price,
                            "tp": tp_price,
                            "ok": True,
                            "sl_order_id": result.get("sl_order", {}).get("orderId"),
                            "tp_orders": len(result.get("tp_orders", []))
                        })
                    else:
                        error = result.get("errors", ["unknown error"])[0]
                        logger.error(f"  ❌ Failed: {error}")
                        errors.append({"symbol": symbol, "error": error})
                        
            except Exception as e:
                logger.error(f"  ❌ Exception: {e}")
                errors.append({"symbol": symbol, "error": str(e)})
        
        summary = {
            "ok": True,
            "protected": len(protected),
            "errors": len(errors),
            "protected_positions": protected,
            "failed_positions": errors,
            "dry_run": dry_run
        }
        
        logger.info(f"\n{'='*60}")
        logger.info(f"📊 SUMMARY: Protected {len(protected)} positions, {len(errors)} errors")
        logger.info(f"{'='*60}\n")
        
        return summary
        
    except Exception as e:
        logger.error(f"❌ protect_all_open_positions failed: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🛡️  AlgoGPT Position Protector")
    print("="*60)
    
    # First, show what WOULD happen (dry run)
    print("\n📋 DRY RUN - Showing what would be protected:\n")
    result = asyncio.run(protect_all_open_positions(dry_run=True))
    
    if result.get("protected", 0) > 0:
        print(f"\n✅ Ready to protect {result['protected']} positions")
        print("\nTo actually attach TP/SL, run:")
        print("  python protect_existing_positions.py --apply")
    else:
        print("\nℹ️  No open positions to protect")
