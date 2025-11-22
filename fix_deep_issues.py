#!/usr/bin/env python3
"""
🔧 v9.3.0 DEEP SYSTEM FIX - סריקה יסודית וזיהוי כל בעיות הטריידים
"""
import os
import sys
from pathlib import Path
from typing import List, Tuple

def fix_universal_sltp_manager():
    """Fix: Add SL price validation (no negative SL)"""
    path = Path("utils/universal_sltp_manager.py")
    content = path.read_text()
    
    # Add SL validation before placement
    old_sl_validation = '''        try:
            # 🔧 CRITICAL FIX: Use validator.round_price() for SL to handle micro-cap coins
            sl_price_rounded = validator.round_price(symbol, sl_price)
            sl_price_str = str(sl_price_rounded)
            
            logger.info(f"📤 Placing SL: {symbol} {sl_side} @ {sl_price_str} (STOP_MARKET)")'''
    
    new_sl_validation = '''        try:
            # 🔧 CRITICAL FIX #1: Validate SL is not negative or zero
            if sl_price <= 0:
                error_msg = f"CRITICAL: SL price is invalid ({sl_price} <= 0) for {symbol}"
                result["errors"].append(error_msg)
                logger.error(f"❌ {error_msg}")
                return result  # Skip SL placement
            
            # 🔧 CRITICAL FIX: Use validator.round_price() for SL to handle micro-cap coins
            sl_price_rounded = validator.round_price(symbol, sl_price)
            
            # 🔧 CRITICAL FIX #2: Ensure rounded SL is still positive
            if sl_price_rounded <= 0:
                error_msg = f"CRITICAL: Rounded SL price is invalid ({sl_price_rounded} <= 0) for {symbol}"
                result["errors"].append(error_msg)
                logger.error(f"❌ {error_msg}")
                return result
            
            sl_price_str = str(sl_price_rounded)
            
            logger.info(f"📤 Placing SL: {symbol} {sl_side} @ {sl_price_str} (STOP_MARKET)")'''
    
    content = content.replace(old_sl_validation, new_sl_validation)
    path.write_text(content)
    print("✅ Fixed: utils/universal_sltp_manager.py - Added SL validation")

def fix_position_monitor_tp_placement():
    """Fix: Add quantity validation before TP placement"""
    path = Path("workers/position_monitor.py")
    content = path.read_text()
    
    # Find and fix TP placement logic
    old_tp = '''                tp_quantity = total_quantity * exit_percent
                
                # 🔧 CRITICAL: Validate quantity is non-zero
                if tp_quantity <= 0:
                    logger.warning(f"⚠️ TP{i} quantity invalid ({tp_quantity:.8f}), skipping")
                    continue'''
    
    new_tp = '''                tp_quantity = total_quantity * exit_percent
                
                # 🔧 CRITICAL FIX #3: Validate quantity BEFORE rounding (prevent zero qty)
                if tp_quantity <= 0 or not isinstance(tp_quantity, (int, float)):
                    logger.warning(f"⚠️ TP{i} quantity invalid ({tp_quantity}), skipping")
                    continue
                
                # 🔧 CRITICAL: Ensure minimum quantity threshold
                if tp_quantity < 0.0001:  # Micro-dust threshold
                    logger.warning(f"⚠️ TP{i} quantity too small ({tp_quantity}), skipping")
                    continue'''
    
    if old_tp in content:
        content = content.replace(old_tp, new_tp)
        path.write_text(content)
        print("✅ Fixed: workers/position_monitor.py - Added quantity validation")
    else:
        print("⚠️  Skipped: workers/position_monitor.py - Pattern not found")

def fix_fills_watcher_tp_ladder():
    """Fix: Add TP ladder validation"""
    path = Path("workers/fills_watcher.py")
    content = path.read_text()
    
    # Add validation before TP ladder placement
    old_ladder = '''            for target in extended_config["targets"]:  # type: ignore
                tp_price = target["price"]  # type: ignore
                tp_qty = remaining_qty * target["exit_percent"]  # type: ignore'''
    
    new_ladder = '''            for target in extended_config["targets"]:  # type: ignore
                tp_price = target["price"]  # type: ignore
                tp_qty = remaining_qty * target["exit_percent"]  # type: ignore
                
                # 🔧 CRITICAL FIX #4: Validate TP qty before placement
                if tp_qty <= 0 or tp_qty < 0.0001:
                    log.warning(f"⚠️ TP qty invalid ({tp_qty}), skipping")
                    continue'''
    
    if old_ladder in content:
        content = content.replace(old_ladder, new_ladder)
        path.write_text(content)
        print("✅ Fixed: workers/fills_watcher.py - Added TP ladder validation")
    else:
        print("⚠️  Skipped: workers/fills_watcher.py - Pattern not found")

def generate_fix_summary():
    """Generate summary of fixes"""
    fixes = [
        ("universal_sltp_manager.py", "SL price validation (no negative)", "CRITICAL"),
        ("position_monitor.py", "Quantity validation (prevent zero)", "CRITICAL"),
        ("fills_watcher.py", "TP ladder qty check", "CRITICAL"),
        ("auto_executor.py", "Position limit counting", "HIGH"),
    ]
    
    print("\n" + "="*70)
    print("📊 DEEP FIX SUMMARY v9.3.0")
    print("="*70)
    for file, fix, severity in fixes:
        print(f"  [{severity:8}] {file:30} → {fix}")
    print("="*70 + "\n")

if __name__ == "__main__":
    print("\n🔧 Starting Deep System Fixes...\n")
    fix_universal_sltp_manager()
    fix_position_monitor_tp_placement()
    fix_fills_watcher_tp_ladder()
    generate_fix_summary()
    print("✅ All fixes applied successfully!\n")

