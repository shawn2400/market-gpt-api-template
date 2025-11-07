#!/usr/bin/env python3
"""
EMERGENCY: Add SL/TP to SOLUSDT position
Entry: 156.21
Mark: 156.71
Side: LONG
Leverage: 4x
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.binance_client import get_futures_client
from utils.sl_manager import ZeroGapSLManager
from utils.tp_ladder import TPLadder

SYMBOL = "SOLUSDT"
ENTRY_PRICE = 156.21
QUANTITY = 3.83  
SIDE = "LONG"
POSITION_SIDE = "LONG"

ATR = 1.23

SL_PRICE = round(ENTRY_PRICE - (ATR * 1.5), 2)  
TP1_PRICE = round(ENTRY_PRICE + (ATR * 1.2), 2)  
TP2_PRICE = round(ENTRY_PRICE + (ATR * 2.0), 2)  
TP3_PRICE = round(ENTRY_PRICE + (ATR * 2.8), 2)  

print(f"🚨 EMERGENCY SL/TP Setup for {SYMBOL}")
print(f"Position: {SIDE} {QUANTITY} @ ${ENTRY_PRICE}")
print(f"SL: ${SL_PRICE} (-{round((ENTRY_PRICE - SL_PRICE)/ENTRY_PRICE*100, 2)}%)")
print(f"TP1: ${TP1_PRICE} (+{round((TP1_PRICE - ENTRY_PRICE)/ENTRY_PRICE*100, 2)}%)")
print(f"TP2: ${TP2_PRICE} (+{round((TP2_PRICE - ENTRY_PRICE)/ENTRY_PRICE*100, 2)}%)")
print(f"TP3: ${TP3_PRICE} (+{round((TP3_PRICE - ENTRY_PRICE)/ENTRY_PRICE*100, 2)}%)")
print()

try:
    client = get_futures_client()
    
    print("1️⃣ Setting up STOP LOSS...")
    sl_manager = ZeroGapSLManager(client)
    sl_result = sl_manager.safe_replace_sl(
        symbol=SYMBOL,
        new_stop_price=SL_PRICE,
        qty=QUANTITY,
        side=SIDE,
        position_side=POSITION_SIDE
    )
    
    if sl_result.get("success"):
        print(f"✅ SL placed successfully: Order #{sl_result.get('new_order_id')}")
    else:
        print(f"❌ SL failed: {sl_result.get('error')}")
        sys.exit(1)
    
    print("\n2️⃣ Setting up TAKE PROFIT ladder...")
    tp_manager = TPLadder(client)
    tp_result = tp_manager.set_tp_ladder(
        symbol=SYMBOL,
        entry_price=ENTRY_PRICE,
        qty=QUANTITY,
        side=SIDE,
        tp_prices=[TP1_PRICE, TP2_PRICE, TP3_PRICE],
        position_side=POSITION_SIDE
    )
    
    if tp_result.get("success"):
        orders = tp_result.get('placed_orders', [])
        print(f"✅ TP ladder placed successfully: {len(orders)} orders")
        for i, order_id in enumerate(orders, 1):
            print(f"   TP{i}: Order #{order_id}")
    else:
        print(f"❌ TP failed: {tp_result.get('error')}")
        sys.exit(1)
    
    print("\n🎉 SUCCESS! Position is now protected with SL/TP!")
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
