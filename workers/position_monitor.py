#!/usr/bin/env python3
# workers/position_monitor.py
"""
Position Monitor Worker - Periodic PNL & Status Reports
Runs every 30-60 minutes and sends consolidated Telegram updates
"""
import os
import sys
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.binance_client import _init_client as get_client, futures_cancel_all_orders
from utils.alerts import send_telegram_message

try:
    from utils.telegram_digest import get_digest
except Exception:
    def get_digest():  # type: ignore
        class MockDigest:
            def add_health_alert(self, *args, **kwargs):  # type: ignore
                pass
        return MockDigest()

try:
    from utils.position_manager import manage_once as add_sl_tp_protection
except Exception:
    add_sl_tp_protection = None  # type: ignore

def cleanup_orders_for_closed_positions(closed_symbols: List[str]) -> None:
    """
    Cancel all remaining orders for positions that have been closed.
    This prevents orphaned TP/SL/Trailing orders from staying active.
    
    SAFETY: Only cancels orders for symbols with ZERO position size across all sides.
    In Hedge Mode, verifies both LONG and SHORT are flat before cleanup.
    
    Args:
        closed_symbols: List of symbols that have been closed
    """
    if not closed_symbols:
        return
    
    for symbol in closed_symbols:
        try:
            # SAFETY CHECK: Verify position is actually ZERO on all sides before cleanup
            client = get_client()
            if client:
                positions = client.futures_position_information(symbol=symbol)
                total_amt = sum(abs(float(p.get("positionAmt", 0))) for p in positions)
                if total_amt > 0:
                    logger.warning(f"⚠️ Skipping cleanup for {symbol}: Position still active (amt={total_amt})")
                    continue
            
            logger.info(f"🧹 Cleaning up orders for closed position: {symbol}")
            result = futures_cancel_all_orders(symbol)
            if result.get("ok"):
                logger.info(f"✅ Cancelled all orders for {symbol}")
            else:
                logger.warning(f"⚠️ Failed to cancel orders for {symbol}: {result.get('error')}")
        except Exception as e:
            logger.error(f"❌ Error cancelling orders for {symbol}: {e}")

async def ensure_positions_protected() -> None:
    """
    🛡️ LAYER 3: Emergency Protection + Auto-protect
    
    1. First checks if positions have SL/TP using Emergency Protection
    2. If UNPROTECTED → Emergency close + Circuit breaker
    3. If protected → Normal auto-protect (BE, trailing, etc)
    
    Runs every 30 seconds to ensure LIVE protection + cleanup closed positions.
    """
    global _previous_positions
    
    if not ENABLE_AUTO_PROTECT:
        return
    
    try:
        positions = get_active_positions()
        current_symbols = {p["symbol"] for p in positions}
        
        # 🧹 CRITICAL: Detect and cleanup closed positions EVERY 30 seconds
        closed_positions = []
        for prev_symbol in _previous_positions.keys():
            if prev_symbol not in current_symbols:
                closed_positions.append(prev_symbol)
        
        if closed_positions:
            logger.info(f"🔍 Detected {len(closed_positions)} closed position(s): {', '.join(closed_positions)}")
            cleanup_orders_for_closed_positions(closed_positions)
        
        # Update tracking
        _previous_positions = {p["symbol"]: p for p in positions}
        
        if not positions:
            return
        
        # 🛡️ CRITICAL: Emergency Protection Check FIRST
        try:
            from utils.emergency_protection import get_emergency_protection
            emergency = get_emergency_protection()
            
            closed_count = emergency.enforce_protection()
            if closed_count > 0:
                logger.critical(f"🚨 Emergency Protection closed {closed_count} unprotected positions!")
                return
        
        except Exception as e:
            logger.error(f"❌ Emergency Protection check failed: {e}", exc_info=True)
        
        # Regular auto-protect for protected positions
        if add_sl_tp_protection is None:
            logger.warning("⚠️ position_manager.manage_once not available - skipping auto-protect")
            return
        
        for pos in positions:
            symbol = pos.get("symbol", "")
            amt = float(pos.get("positionAmt", 0))
            
            if amt == 0:
                continue
            
            try:
                result = await add_sl_tp_protection(symbol=symbol)
                
                if result.get("skipped"):
                    logger.debug(f"⏭️ {symbol}: {result.get('reason', 'skipped')}")
                elif result.get("ok"):
                    actions = []
                    if result.get("sl_updated") or result.get("sl_placed"):
                        actions.append("SL")
                    if result.get("tp_ladder_placed") or result.get("tp_count", 0) > 0:
                        tp_count = result.get("tp_count", result.get("tp_ladder_count", 0))
                        actions.append(f"TP×{tp_count}")
                    if result.get("trail_placed"):
                        actions.append("Trail")
                    
                    if actions:
                        logger.info(f"✅ {symbol}: Protected [{', '.join(actions)}]")
                    else:
                        logger.debug(f"✓ {symbol}: Already protected")
                elif not result.get("ok"):
                    logger.warning(f"⚠️ {symbol}: Protection failed - {result.get('error', 'unknown')}")
            
            except Exception as e:
                logger.error(f"❌ {symbol}: Auto-protect error: {e}", exc_info=True)
        
    except Exception as e:
        logger.error(f"❌ ensure_positions_protected failed: {e}")

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger("position_monitor")

# Configuration
REPORT_INTERVAL_SEC = int(os.getenv("POSITION_REPORT_INTERVAL_SEC", "1800"))  # 30 minutes
AUTO_PROTECT_INTERVAL_SEC = int(os.getenv("AUTO_PROTECT_INTERVAL_SEC", "30"))  # 30 seconds for SL/TP checks
ENABLE_POSITION_MONITOR = os.getenv("ENABLE_POSITION_MONITOR", "1").lower() in ("1", "true", "yes")
ENABLE_AUTO_PROTECT = os.getenv("ENABLE_AUTO_PROTECT", "1").lower() in ("1", "true", "yes")
POSITION_ALERT_LEVEL = os.getenv("POSITION_ALERT_LEVEL", "critical").lower()
POSITION_PNL_THRESHOLD = float(os.getenv("POSITION_PNL_THRESHOLD_PCT", "10.0"))

# 🎯 TRAILING TP CONFIGURATION
ENABLE_TRAILING_TP = os.getenv("ENABLE_TRAILING_TP", "1").lower() in ("1", "true", "yes")
TRAILING_ACTIVATION_PCT = float(os.getenv("TRAILING_ACTIVATION_PCT", "25.0"))  # Activate at 25% profit
TRAILING_DISTANCE_PCT = float(os.getenv("TRAILING_DISTANCE_PCT", "15.0"))  # Close at 15% from peak

# Track previous state to detect changes
_previous_positions: Dict[str, Dict[str, Any]] = {}
_last_position_count = 0

# 🎯 TRAILING TP SYSTEM - Track peak prices and trailing state
_trailing_positions: Dict[str, Dict[str, Any]] = {}
# Structure: {symbol: {peak_price, activation_time, trailing_distance, entry_price, side}}

def calculate_pnl_percent(entry_price: float, current_price: float, side: str) -> float:
    """Calculate PNL percentage based on position side"""
    if entry_price <= 0:
        return 0.0
    
    if side == "LONG":
        return ((current_price - entry_price) / entry_price) * 100
    else:  # SHORT
        return ((entry_price - current_price) / entry_price) * 100

def should_activate_trailing(position: Dict[str, Any]) -> bool:
    """Check if trailing TP should be activated for this position"""
    symbol = position.get("symbol", "")
    
    # Already activated
    if symbol in _trailing_positions:
        return False
    
    entry = float(position.get("entryPrice", 0))
    mark = float(position.get("markPrice", 0))
    amt = float(position.get("positionAmt", 0))
    
    if entry <= 0 or mark <= 0:
        return False
    
    side = "LONG" if amt > 0 else "SHORT"
    pnl_pct = calculate_pnl_percent(entry, mark, side)
    
    # Activate if profit >= threshold
    return pnl_pct >= TRAILING_ACTIVATION_PCT

def activate_trailing(position: Dict[str, Any]) -> None:
    """Activate trailing TP for a position"""
    symbol = position.get("symbol", "")
    entry = float(position.get("entryPrice", 0))
    mark = float(position.get("markPrice", 0))
    amt = float(position.get("positionAmt", 0))
    side = "LONG" if amt > 0 else "SHORT"
    
    pnl_pct = calculate_pnl_percent(entry, mark, side)
    
    _trailing_positions[symbol] = {
        "peak_price": mark,
        "activation_time": datetime.now(timezone.utc),
        "trailing_distance": TRAILING_DISTANCE_PCT,
        "entry_price": entry,
        "side": side,
        "activation_pnl": pnl_pct
    }
    
    logger.info(f"🎯 Trailing TP activated for {symbol} | PNL: +{pnl_pct:.1f}% | Peak: {mark:.4f}")
    
    # Send Telegram notification
    try:
        message = (
            f"🎯 <b>TRAILING TP ACTIVATED</b>\n\n"
            f"Symbol: <b>{symbol}</b>\n"
            f"Side: {side}\n"
            f"Entry: <code>{entry:.4f}</code>\n"
            f"Current: <code>{mark:.4f}</code>\n"
            f"Profit: <b>+{pnl_pct:.1f}%</b>\n\n"
            f"📊 Will close if price drops {TRAILING_DISTANCE_PCT}% from peak\n"
            f"🔒 Protecting your profits!"
        )
        send_telegram_message(message)
    except Exception as e:
        logger.warning(f"Failed to send trailing activation alert: {e}")

def update_trailing_peak(position: Dict[str, Any]) -> None:
    """Update peak price if new high/low reached"""
    symbol = position.get("symbol", "")
    if symbol not in _trailing_positions:
        return
    
    trailing_data = _trailing_positions[symbol]
    mark = float(position.get("markPrice", 0))
    peak = trailing_data["peak_price"]
    side = trailing_data["side"]
    
    # Update peak if new extreme reached
    if side == "LONG" and mark > peak:
        old_peak = peak
        trailing_data["peak_price"] = mark
        logger.info(f"📈 {symbol}: New peak {mark:.4f} (was {old_peak:.4f})")
    elif side == "SHORT" and mark < peak:
        old_peak = peak
        trailing_data["peak_price"] = mark
        logger.info(f"📉 {symbol}: New peak {mark:.4f} (was {old_peak:.4f})")

def should_close_by_trailing(position: Dict[str, Any]) -> tuple[bool, float, str]:
    """
    Check if position should be closed based on trailing TP logic
    Returns: (should_close, current_pnl_pct, reason)
    """
    symbol = position.get("symbol", "")
    if symbol not in _trailing_positions:
        return False, 0.0, ""
    
    trailing_data = _trailing_positions[symbol]
    mark = float(position.get("markPrice", 0))
    peak = trailing_data["peak_price"]
    side = trailing_data["side"]
    entry = trailing_data["entry_price"]
    
    if peak <= 0 or mark <= 0:
        return False, 0.0, ""
    
    # Calculate drawdown from peak (absolute percentage)
    if side == "LONG":
        # For LONG: peak is highest price reached
        # Drawdown when price drops from peak
        drawdown_pct = abs((peak - mark) / peak) * 100
    else:  # SHORT
        # For SHORT: peak is lowest price reached (best for short)
        # Drawdown when price rises from peak
        drawdown_pct = abs((mark - peak) / peak) * 100
    
    current_pnl = calculate_pnl_percent(entry, mark, side)
    
    # Close if drawdown >= trailing distance
    if drawdown_pct >= TRAILING_DISTANCE_PCT:
        direction = "dropped" if side == "LONG" else "rose"
        reason = f"Price {direction} {drawdown_pct:.1f}% from peak {peak:.4f}"
        logger.info(f"🎯 {symbol} trailing close triggered: {reason} | Current PnL: +{current_pnl:.1f}%")
        return True, current_pnl, reason
    
    return False, current_pnl, ""

async def execute_trailing_close(position: Dict[str, Any], pnl_pct: float, reason: str) -> None:
    """Execute market close for trailing TP trigger"""
    symbol = position.get("symbol", "")
    amt = float(position.get("positionAmt", 0))
    mark = float(position.get("markPrice", 0))
    
    try:
        client = get_client()
        if not client:
            logger.error(f"Cannot close {symbol}: Client not available")
            return
        
        side = "SELL" if amt > 0 else "BUY"
        qty = abs(amt)
        
        logger.info(f"🎯 Executing trailing close: {symbol} | {side} {qty} @ market | PNL: +{pnl_pct:.1f}%")
        
        # Place market order with reduceOnly
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=qty,
            reduceOnly=True
        )
        
        logger.info(f"✅ Trailing close executed: {symbol} | Order ID: {order.get('orderId')}")
        
        # Remove from trailing tracking
        trailing_data = _trailing_positions.pop(symbol, {})
        activation_time = trailing_data.get("activation_time", datetime.now(timezone.utc))
        duration = (datetime.now(timezone.utc) - activation_time).total_seconds() / 60
        
        # Send Telegram notification
        message = (
            f"✅ <b>TRAILING TP CLOSED</b>\n\n"
            f"Symbol: <b>{symbol}</b>\n"
            f"Side: {side}\n"
            f"Qty: <code>{qty}</code>\n"
            f"Price: <code>{mark:.4f}</code>\n"
            f"Profit: <b>+{pnl_pct:.1f}%</b>\n\n"
            f"📊 {reason}\n"
            f"⏱️ Trailing duration: {duration:.1f} min\n"
            f"🎯 <b>Profit secured!</b>"
        )
        send_telegram_message(message)
        
    except Exception as e:
        logger.error(f"❌ Failed to execute trailing close for {symbol}: {e}")

async def check_and_update_trailing_tp() -> None:
    """
    Main trailing TP logic - runs every 30 seconds
    1. Activate trailing for positions at profit threshold
    2. Update peak prices for active trailing positions
    3. Close positions that hit trailing stop
    """
    if not ENABLE_TRAILING_TP:
        return
    
    try:
        positions = get_active_positions()
        if not positions:
            return
        
        for pos in positions:
            symbol = pos.get("symbol", "")
            
            # Step 1: Check if should activate trailing
            if should_activate_trailing(pos):
                activate_trailing(pos)
            
            # Step 2: Update peak if trailing active
            if symbol in _trailing_positions:
                update_trailing_peak(pos)
            
            # Step 3: Check if should close by trailing
            should_close, pnl_pct, reason = should_close_by_trailing(pos)
            if should_close:
                await execute_trailing_close(pos, pnl_pct, reason)
    
    except Exception as e:
        logger.error(f"❌ check_and_update_trailing_tp failed: {e}")

def get_active_positions() -> List[Dict[str, Any]]:
    """Get all active positions from Binance"""
    try:
        client = get_client()
        if not client:
            return []
        
        all_positions = client.futures_position_information()
        # Filter only positions with size > 0
        active = [
            p for p in all_positions 
            if abs(float(p.get("positionAmt", 0))) > 0
        ]
        return active
    except Exception as e:
        logger.error(f"Failed to get positions: {e}")
        return []

def calculate_total_pnl(positions: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate total unrealized and realized PNL"""
    unrealized = sum(float(p.get("unRealizedProfit", 0)) for p in positions)
    # Note: Binance doesn't provide realized PNL in position endpoint
    # You may need to query income history for accurate realized PNL
    return {
        "unrealized_pnl": unrealized,
        "position_count": len(positions)
    }

def format_position_summary(positions: List[Dict[str, Any]]) -> str:
    """Format positions into readable message"""
    if not positions:
        return "📊 <b>No active positions</b>\n\n💤 Waiting for quality setups..."
    
    lines = ["📊 <b>ACTIVE POSITIONS REPORT</b>\n"]
    
    total_pnl = 0.0
    for p in positions:
        symbol = p.get("symbol", "")
        amt = float(p.get("positionAmt", 0))
        entry = float(p.get("entryPrice", 0))
        mark = float(p.get("markPrice", 0))
        upnl = float(p.get("unRealizedProfit", 0))
        lev = int(p.get("leverage", 1))
        
        side_emoji = "🟢 LONG" if amt > 0 else "🔴 SHORT"
        pnl_emoji = "💰" if upnl > 0 else "📉"
        
        lines.append(f"{side_emoji} <b>{symbol}</b>")
        lines.append(f"  Entry: <code>{entry:.2f}</code> | Mark: <code>{mark:.2f}</code>")
        lines.append(f"  {pnl_emoji} PNL: <code>${upnl:.2f}</code> | Lev: x{lev}")
        lines.append(f"  Qty: <code>{abs(amt):.4f}</code>\n")
        
        total_pnl += upnl
    
    # Summary
    total_emoji = "✅" if total_pnl > 0 else "⚠️"
    lines.append(f"{'='*30}")
    lines.append(f"{total_emoji} <b>Total Unrealized PNL: ${total_pnl:.2f}</b>")
    lines.append(f"📈 Active Trades: {len(positions)}")
    lines.append(f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    
    return "\n".join(lines)

def detect_significant_changes(positions: List[Dict[str, Any]]) -> tuple[bool, str]:
    """Detect if there are significant changes worth alerting"""
    global _previous_positions, _last_position_count
    
    current_count = len(positions)
    current_symbols = {p["symbol"]: p for p in positions}
    
    new_positions = []
    closed_positions = []
    large_pnl_changes = []
    
    for symbol, pos in current_symbols.items():
        if symbol not in _previous_positions:
            new_positions.append(symbol)
    
    for symbol, prev_pos in _previous_positions.items():
        if symbol not in current_symbols:
            closed_positions.append(symbol)
    
    # 🧹 CLEANUP: Cancel all remaining orders for closed positions
    if closed_positions:
        cleanup_orders_for_closed_positions(closed_positions)
    
    for symbol, pos in current_symbols.items():
        if symbol in _previous_positions:
            prev_pnl = float(_previous_positions[symbol].get("unRealizedProfit", 0))
            curr_pnl = float(pos.get("unRealizedProfit", 0))
            entry = float(pos.get("entryPrice", 1))
            
            if entry > 0:
                pnl_change_pct = abs((curr_pnl - prev_pnl) / entry * 100)
                if pnl_change_pct >= POSITION_PNL_THRESHOLD:
                    large_pnl_changes.append((symbol, pnl_change_pct, curr_pnl))
    
    _previous_positions = current_symbols.copy()
    _last_position_count = current_count
    
    reasons = []
    if new_positions:
        reasons.append(f"{len(new_positions)} new position(s): {', '.join(new_positions)}")
    if closed_positions:
        reasons.append(f"{len(closed_positions)} closed: {', '.join(closed_positions)}")
    if large_pnl_changes:
        reasons.append(f"{len(large_pnl_changes)} large PnL changes (>{POSITION_PNL_THRESHOLD}%)")
    
    should_alert = bool(new_positions or closed_positions or large_pnl_changes)
    reason = " | ".join(reasons) if reasons else "No significant changes"
    
    return should_alert, reason

async def send_position_report():
    """Send consolidated position report to Digest Queue (batched delivery)"""
    try:
        positions = get_active_positions()
        digest = get_digest()
        
        # שליחה אוטומטית כל 30 דקות - אין תלות ברמת ההתראה
        if POSITION_ALERT_LEVEL == "all":
            logger.info(f"Queuing scheduled report: {len(positions)} positions")
            message = format_position_summary(positions)
            digest.add_health_alert(level="INFO", message=f"📊 Position Report\n\n{message}")
        elif POSITION_ALERT_LEVEL == "critical":
            should_alert, reason = detect_significant_changes(positions)
            if not should_alert:
                logger.info(f"Skipping notification: {reason}")
                return
            logger.info(f"Queuing alert: {reason}")
            message = format_position_summary(positions)
            digest.add_health_alert(level="WARNING", message=f"⚠️ Position Alert: {reason}\n\n{message}")
        
        logger.info(f"Position report queued for digest: {len(positions)} active positions")
    except Exception as e:
        logger.error(f"Failed to queue position report: {e}")

async def monitor_loop():
    """Main monitoring loop - dual frequency for reports and protection"""
    logger.info(
        f"Position Monitor started | "
        f"Reports: {REPORT_INTERVAL_SEC}s | "
        f"Auto-Protect: {AUTO_PROTECT_INTERVAL_SEC}s | "
        f"Trailing TP: {'ON' if ENABLE_TRAILING_TP else 'OFF'} | "
        f"Protection: {'ON' if ENABLE_AUTO_PROTECT else 'OFF'}"
    )
    
    if ENABLE_TRAILING_TP:
        logger.info(
            f"🎯 Trailing TP Config: Activate at {TRAILING_ACTIVATION_PCT}%, "
            f"Close at {TRAILING_DISTANCE_PCT}% from peak"
        )
    
    last_report_time = 0
    
    while True:
        current_time = time.time()
        
        try:
            # 🎯 TRAILING TP - Check and update every 30 seconds
            if ENABLE_TRAILING_TP:
                await check_and_update_trailing_tp()
        except Exception as e:
            logger.error(f"Error in trailing TP: {e}")
        
        try:
            if ENABLE_AUTO_PROTECT:
                await ensure_positions_protected()
        except Exception as e:
            logger.error(f"Error in auto-protect: {e}")
        
        if current_time - last_report_time >= REPORT_INTERVAL_SEC:
            try:
                await send_position_report()
                last_report_time = current_time
            except Exception as e:
                logger.error(f"Error in report: {e}")
        
        await asyncio.sleep(AUTO_PROTECT_INTERVAL_SEC)

def main():
    if not ENABLE_POSITION_MONITOR:
        logger.info("Position monitor disabled (ENABLE_POSITION_MONITOR=0)")
        return
    
    asyncio.run(monitor_loop())

if __name__ == "__main__":
    main()
