#!/usr/bin/env python3
"""
Cleanup Orphaned Orders Script
Cancels all remaining orders for positions that have been closed.
Useful for cleaning up TP/SL/Trailing orders left after position closure.

Usage:
    python scripts/cleanup_orphaned_orders.py             # Clean all symbols with 0 position
    python scripts/cleanup_orphaned_orders.py SOLUSDT     # Clean specific symbol
    python scripts/cleanup_orphaned_orders.py --all       # Clean ALL open orders (dangerous!)
"""
import os
import sys
from typing import List, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.binance_client import _init_client as get_client, futures_cancel_all_orders


def get_positions_with_zero_amt() -> List[str]:
    """Get all symbols that have open orders but zero position amount"""
    try:
        client = get_client()
        if not client:
            print("❌ Failed to initialize Binance client")
            return []
        
        # Get all positions
        all_positions = client.futures_position_information()
        
        # Get symbols with zero position but might have orders
        zero_position_symbols = [
            p["symbol"] for p in all_positions 
            if abs(float(p.get("positionAmt", 0))) == 0
        ]
        
        # Check which ones have open orders
        orphaned_symbols = []
        for symbol in zero_position_symbols:
            try:
                open_orders = client.futures_get_open_orders(symbol=symbol)
                if open_orders:
                    orphaned_symbols.append(symbol)
                    print(f"🔍 Found {len(open_orders)} orphaned order(s) for {symbol}")
            except Exception as e:
                print(f"⚠️ Error checking orders for {symbol}: {e}")
        
        return orphaned_symbols
    
    except Exception as e:
        print(f"❌ Error getting positions: {e}")
        return []


def cleanup_symbol(symbol: str, force: bool = False, reduce_only_filter: bool = True) -> bool:
    """
    Cancel all orders for a specific symbol.
    
    Args:
        symbol: Symbol to clean
        force: If True, skip position safety check (DANGEROUS)
        reduce_only_filter: If True, only cancel reduceOnly orders (safer)
    """
    try:
        client = get_client()
        if not client:
            print(f"❌ Failed to initialize Binance client")
            return False
        
        # SAFETY CHECK: Verify position is ZERO on ALL sides (Hedge Mode)
        if not force:
            positions = client.futures_position_information(symbol=symbol)
            total_amt = sum(abs(float(p.get("positionAmt", 0))) for p in positions)
            if total_amt > 0:
                print(f"⚠️ SKIPPED {symbol}: Position still active (total amt={total_amt})")
                print(f"   Details: {[(p.get('positionSide'), p.get('positionAmt')) for p in positions]}")
                print(f"   Use --force to cancel orders anyway (DANGEROUS!)")
                return False
        
        # Get open orders
        open_orders = client.futures_get_open_orders(symbol=symbol)
        if not open_orders:
            print(f"✓ {symbol}: No open orders to cancel")
            return True
        
        # Filter to reduceOnly orders only (safer)
        if reduce_only_filter:
            orders_to_cancel = [o for o in open_orders if bool(o.get("reduceOnly"))]
            if not orders_to_cancel:
                print(f"✓ {symbol}: No reduceOnly orders to cancel ({len(open_orders)} non-reduce orders remain)")
                return True
            print(f"🧹 Cleaning {len(orders_to_cancel)} reduceOnly order(s) for {symbol} ({len(open_orders)} total)...")
        else:
            orders_to_cancel = open_orders
            print(f"🧹 Cleaning ALL {len(orders_to_cancel)} order(s) for {symbol}...")
        
        # Cancel orders individually to handle partial failures
        cancelled_count = 0
        for order in orders_to_cancel:
            try:
                client.futures_cancel_order(symbol=symbol, orderId=order.get("orderId"))
                cancelled_count += 1
            except Exception as e:
                print(f"  ⚠️ Failed to cancel order {order.get('orderId')}: {e}")
        
        if cancelled_count == len(orders_to_cancel):
            print(f"✅ {symbol}: Cancelled all {cancelled_count} order(s) successfully")
            return True
        else:
            print(f"⚠️ {symbol}: Cancelled {cancelled_count}/{len(orders_to_cancel)} orders (some failed)")
            return False
    
    except Exception as e:
        print(f"❌ Error cleaning {symbol}: {e}")
        return False


def main():
    """Main cleanup logic"""
    import sys
    
    print("🧹 Orphaned Orders Cleanup Script")
    print("=" * 50)
    
    args = sys.argv[1:]
    
    if "--help" in args or "-h" in args:
        print(__doc__)
        return
    
    force = "--force" in args or "-f" in args
    clean_all = "--all" in args
    
    if force:
        args = [a for a in args if a not in ("--force", "-f")]
        print("⚠️ FORCE MODE ENABLED - Will cancel orders even if position is active!")
        print()
    
    if clean_all:
        print("⚠️ WARNING: This will cancel ALL open orders for ALL symbols!")
        confirm = input("Type 'YES' to confirm: ")
        if confirm != "YES":
            print("❌ Cancelled")
            return
        
        orphaned = get_positions_with_zero_amt()
        if not orphaned:
            print("✓ No orphaned orders found")
            return
        
        print(f"\n🧹 Cleaning {len(orphaned)} symbol(s) with orphaned orders...")
        print()
        
        for symbol in orphaned:
            cleanup_symbol(symbol, force=force)
    
    elif args:
        # Clean specific symbols
        for symbol in args:
            cleanup_symbol(symbol.upper(), force=force)
    
    else:
        # Default: find and clean symbols with zero position and open orders
        print("🔍 Scanning for orphaned orders (symbols with 0 position but open orders)...")
        print()
        
        orphaned = get_positions_with_zero_amt()
        
        if not orphaned:
            print("✅ No orphaned orders found!")
            return
        
        print(f"\n🧹 Found {len(orphaned)} symbol(s) with orphaned orders:")
        for symbol in orphaned:
            print(f"  - {symbol}")
        
        print()
        confirm = input(f"Cancel all orders for these {len(orphaned)} symbol(s)? (yes/no): ")
        
        if confirm.lower() in ("yes", "y"):
            print()
            for symbol in orphaned:
                cleanup_symbol(symbol, force=force)
        else:
            print("❌ Cancelled")


if __name__ == "__main__":
    main()
