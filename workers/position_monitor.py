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

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger("position_monitor")

# Global state variables for change detection
_previous_positions: Dict[str, Any] = {}
_last_position_count = 0

# 🛡️ FIX: SL placement failure tracking (prevent spam on -2021 errors)
_sl_placement_failures: Dict[str, int] = {}  # symbol -> failure count
_sl_retry_after: Dict[str, float] = {}  # symbol -> timestamp to resume retries
SL_FAILURE_SKIP_CYCLES = 5  # Skip 5 cycles (5 * 30s = 2.5 min cooldown)

# ⚠️ REMOVED: Legacy position_manager import
# add_sl_tp_protection superseded by Trailing TP system to prevent dual-manager conflicts

# 🎯 TRAILING TP SYSTEM (MetaBrain v9.1 Profit Protection)
try:
    import utils.trailing_tp as trailing_tp
    logger.info("✅ Trailing TP system loaded successfully")
except Exception as e:
    trailing_tp = None  # type: ignore
    logger.warning(f"⚠️ Trailing TP unavailable: {e}")

# 🛡️ ADVANCED RISK MANAGER (3-Layer Protection)
try:
    from utils.advanced_risk_manager import get_risk_manager
    from utils.get_klines import get_klines
    from utils.indicators import atr as calculate_atr
    import pandas as pd
    risk_manager = get_risk_manager()
    logger.info("✅ Advanced Risk Manager loaded successfully")
except Exception as e:
    risk_manager = None  # type: ignore
    logger.warning(f"⚠️ Advanced Risk Manager unavailable: {e}")

async def calculate_symbol_atr(symbol: str, period: int = 14) -> float:
    """
    Calculate ATR (Average True Range) for a symbol
    
    Args:
        symbol: Trading symbol (e.g., 'BTCUSDT')
        period: ATR period (default 14)
        
    Returns:
        ATR value, or 0.0 if calculation fails
    """
    try:
        # Get recent candles
        if not get_klines:  # type: ignore
            logger.warning("⚠️ get_klines not available")
            return 0.0
            
        klines = await get_klines(symbol, interval="15m", limit=period + 10)
        if klines is None or len(klines) < period:
            logger.warning(f"⚠️ Insufficient klines for {symbol} ATR calculation")
            return 0.0
        
        # Convert to DataFrame
        if not pd:  # type: ignore
            logger.warning("⚠️ pandas not available")
            return 0.0
        df = pd.DataFrame(klines)
        
        # Calculate ATR
        if not calculate_atr:  # type: ignore
            logger.warning("⚠️ calculate_atr not available")
            return 0.0
        atr_series = calculate_atr(df, period=period)
        if atr_series.empty:
            logger.warning(f"⚠️ Empty ATR series for {symbol}")
            return 0.0
        
        atr_value = float(atr_series.iloc[-1])
        logger.debug(f"📊 {symbol} ATR({period}): {atr_value:.8f}")
        return atr_value
        
    except Exception as e:
        logger.error(f"❌ Failed to calculate ATR for {symbol}: {e}")
        return 0.0


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
            futures_cancel_all_orders(symbol)  # Fire and forget - don't await in sync function
            logger.info(f"✅ Cancelled all orders for {symbol}")
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
        
        # ⚠️ ARCHITECTURE CHANGE: Position Monitor now uses Trailing TP only
        # Legacy add_sl_tp_protection removed to prevent dual-manager conflicts
        
        for pos in positions:
            symbol = pos.get("symbol", "")
            amt = float(pos.get("positionAmt", 0))
            
            if amt == 0:
                continue
            
            # ⚠️ LEGACY SL/TP MANAGEMENT DISABLED - Trailing TP handles all protection
            # add_sl_tp_protection is now superseded by Trailing TP system below
            
            # 🎯 TRAILING TP CHECK (after SL/TP protection)
            if trailing_tp and ENABLE_TRAILING_TP:
                try:
                    mark_price = float(pos.get("markPrice", 0))
                    if mark_price <= 0:
                        continue
                    
                    pos_snapshot = {**pos, "symbol": symbol, "positionAmt": amt, "markPrice": mark_price}
                    
                    if trailing_tp.should_activate_trailing(pos_snapshot):
                        trailing_data = trailing_tp.activate_trailing(pos_snapshot)
                        # 🛡️ FIX: Use Markdown-safe format
                        await send_telegram_message(f"🎯 Trailing TP armed for `{symbol}` @ *{trailing_data['activation_pnl']:.1f}%*")
                    
                    trailing_tp.update_trailing_peak(pos_snapshot)
                    
                    should_close, pnl_pct, reason, trailing_state = trailing_tp.should_close_by_trailing(pos_snapshot)
                    if should_close:
                        from utils.binance_client import futures_create_order, futures_cancel_all_orders
                        
                        position_side = "LONG" if amt > 0 else "SHORT"
                        close_side = "SELL" if position_side == "LONG" else "BUY"
                        
                        close_success = False
                        try:
                            # Step 1: Cancel all existing orders
                            futures_cancel_all_orders(symbol)
                            logger.debug(f"Cancelled all orders for {symbol}")
                            
                            # Step 2: Execute market close with retries
                            for attempt in range(3):
                                try:
                                    order = futures_create_order(
                                        symbol=symbol,
                                        side=close_side,
                                        type="MARKET",
                                        quantity=abs(amt),
                                        reduceOnly=True,
                                        positionSide=position_side
                                    )
                                    order_id = order.get('orderId') if isinstance(order, dict) else 'unknown'
                                    logger.info(f"✅ Trailing TP close executed: {symbol} order {order_id}")
                                    close_success = True
                                    break
                                except Exception as retry_err:
                                    logger.warning(f"⚠️ Trailing TP close attempt {attempt+1}/3 failed for {symbol}: {retry_err}")
                                    if attempt < 2:
                                        await asyncio.sleep(1)  # Brief delay before retry
                            
                            if close_success:
                                trailing_tp.remove_trailing(symbol)
                                # 🛡️ FIX: Use Markdown-safe format
                                await send_telegram_message(f"🚨 Trailing TP exit `{symbol}`: {reason} | PNL *{pnl_pct:+.2f}%*")
                                logger.info(f"🎯 Trailing TP closed {symbol}: {reason} @ {pnl_pct:+.2f}%")
                            else:
                                logger.error(f"❌ Failed to close {symbol} after 3 attempts - keeping trailing state")
                        except Exception as close_err:
                            logger.error(f"❌ Trailing TP close failed for {symbol}: {close_err}")
                            # Keep trailing state if close failed - will retry next cycle
                
                except Exception as err:
                    logger.error(f"❌ {symbol}: Trailing TP error: {err}", exc_info=True)
            
            # 🛡️ ADVANCED RISK MANAGER - 3-LAYER PROTECTION
            if risk_manager:
                try:
                    entry_price = float(pos.get("entryPrice", 0))
                    mark_price = float(pos.get("markPrice", 0))
                    
                    if entry_price <= 0 or mark_price <= 0:
                        continue
                    
                    position_side = "LONG" if amt > 0 else "SHORT"
                    
                    # 🛡️ LAYER 2: Check if within 60-second hold period
                    if risk_manager.is_within_hold_period(symbol):
                        age = risk_manager.get_position_age(symbol)
                        logger.debug(f"⏰ {symbol}: Within hold period ({age:.1f}s / 60s)")
                        continue  # Skip SL activation during hold period
                    
                    # 🛡️ LAYER 2: Check if should force close at 2% max loss
                    should_close, close_reason = risk_manager.should_force_close(pos)
                    if should_close:
                        from utils.binance_client import futures_create_order, futures_cancel_all_orders
                        
                        logger.warning(f"🚨 {symbol}: Force closing - {close_reason}")
                        
                        close_side = "SELL" if position_side == "LONG" else "BUY"
                        
                        try:
                            futures_cancel_all_orders(symbol)
                            order = futures_create_order(
                                symbol=symbol,
                                side=close_side,
                                type="MARKET",
                                quantity=abs(amt),
                                reduceOnly=True,
                                positionSide=position_side
                            )
                            
                            risk_manager.cleanup_closed_position(symbol)
                            # 🛡️ FIX: Use Markdown-safe format
                            await send_telegram_message(
                                f"🚨 *MAX LOSS CAP HIT*\n\n"
                                f"Symbol: `{symbol}`\n"
                                f"Reason: {close_reason}\n\n"
                                f"Closed at market to prevent larger loss"
                            )
                            logger.critical(f"🛡️ {symbol}: Force closed - {close_reason}")
                            continue
                            
                        except Exception as force_close_err:
                            logger.error(f"❌ Failed to force close {symbol}: {force_close_err}")
                    
                    # 🚀 LAYER 3: Check if should move SL to breakeven
                    should_be, be_price = risk_manager.should_activate_breakeven(pos)
                    if should_be:
                        from utils.binance_client import futures_create_order, futures_cancel_all_orders
                        
                        try:
                            # Cancel existing SL orders
                            futures_cancel_all_orders(symbol)
                            
                            # Place new STOP_MARKET at breakeven
                            close_side = "SELL" if position_side == "LONG" else "BUY"
                            
                            sl_order = futures_create_order(
                                symbol=symbol,
                                side=close_side,
                                type="STOP_MARKET",
                                quantity=abs(amt),
                                stopPrice=be_price,
                                reduceOnly=True,
                                positionSide=position_side
                            )
                            
                            logger.info(f"🚀 {symbol}: Breakeven SL activated @ {be_price:.8f}")
                            # 🛡️ FIX: Use Markdown-safe format
                            await send_telegram_message(
                                f"🚀 *Breakeven Activated*\n\n"
                                f"Symbol: `{symbol}`\n"
                                f"SL moved to breakeven: `{be_price:.8f}`\n\n"
                                f"Position now risk-free!"
                            )
                            continue
                            
                        except Exception as be_err:
                            logger.error(f"❌ Failed to set breakeven SL for {symbol}: {be_err}")
                    
                    # 🎯 LAYER 1: Calculate and apply dynamic SL to Binance
                    # 🛡️ FIX: Skip if in cooldown period (after -2021 errors)
                    if symbol in _sl_retry_after and time.time() < _sl_retry_after[symbol]:
                        logger.debug(f"⏸️ {symbol}: SL placement in cooldown, skipping")
                        continue
                    
                    atr = await calculate_symbol_atr(symbol, period=14)
                    if atr > 0:
                        from utils.binance_client import futures_create_order, futures_cancel_all_orders
                        
                        volatility = risk_manager.calculate_volatility(symbol, atr, mark_price)
                        protected_sl = risk_manager.calculate_protected_sl(
                            entry_price, atr, position_side, volatility
                        )
                        
                        try:
                            # Cancel existing SL orders
                            futures_cancel_all_orders(symbol)
                            
                            # Place new STOP_MARKET at protected SL
                            close_side = "SELL" if position_side == "LONG" else "BUY"
                            
                            sl_order = futures_create_order(
                                symbol=symbol,
                                side=close_side,
                                type="STOP_MARKET",
                                quantity=abs(amt),
                                stopPrice=protected_sl,
                                reduceOnly=True,
                                positionSide=position_side
                            )
                            
                            # 🛡️ FIX: On success, clear failure tracking
                            if symbol in _sl_placement_failures:
                                del _sl_placement_failures[symbol]
                            if symbol in _sl_retry_after:
                                del _sl_retry_after[symbol]
                            
                            logger.info(
                                f"🎯 {symbol}: Dynamic SL placed @ {protected_sl:.8f} "
                                f"(ATR={atr:.8f}, Vol={volatility*100:.1f}%)"
                            )
                        except Exception as sl_err:
                            # 🛡️ FIX: Detect -2021 errors and enter cooldown
                            error_code = getattr(sl_err, "code", None)
                            error_msg = str(sl_err)
                            
                            if error_code == -2021 or "-2021" in error_msg or "immediately trigger" in error_msg.lower():
                                _sl_placement_failures[symbol] = _sl_placement_failures.get(symbol, 0) + 1
                                cooldown_time = time.time() + (SL_FAILURE_SKIP_CYCLES * AUTO_PROTECT_INTERVAL_SEC)
                                _sl_retry_after[symbol] = cooldown_time
                                
                                logger.warning(
                                    f"⏸️ {symbol}: SL would trigger immediately (-2021), "
                                    f"entering {SL_FAILURE_SKIP_CYCLES} cycle cooldown "
                                    f"({SL_FAILURE_SKIP_CYCLES * AUTO_PROTECT_INTERVAL_SEC}s)"
                                )
                            else:
                                # Other errors - log normally
                                logger.error(f"❌ Failed to place dynamic SL for {symbol}: {sl_err}")
                    else:
                        logger.debug(f"⚠️ {symbol}: ATR=0, skipping dynamic SL")
                    
                except Exception as risk_err:
                    logger.error(f"❌ {symbol}: Risk Manager error: {risk_err}", exc_info=True)
        
        # 🎯 TRAILING TP CLEANUP: Remove stale symbols
        if trailing_tp and ENABLE_TRAILING_TP:
            try:
                open_syms = {p.get("symbol") for p in positions if abs(float(p.get("positionAmt", 0))) > 0}
                for stale in set(trailing_tp.get_all_trailing_symbols()) - open_syms:
                    trailing_tp.remove_trailing(stale)
                    logger.info(f"🧹 Trailing TP cleanup: removed {stale}")
            except Exception as cleanup_err:
                logger.error(f"❌ Trailing TP cleanup failed: {cleanup_err}")
        
    except Exception as e:
        logger.error(f"❌ ensure_positions_protected failed: {e}")


# Configuration
REPORT_INTERVAL_SEC = int(os.getenv("POSITION_REPORT_INTERVAL_SEC", "1800"))  # 30 minutes
AUTO_PROTECT_INTERVAL_SEC = int(os.getenv("AUTO_PROTECT_INTERVAL_SEC", "30"))  # 30 seconds for SL/TP checks
ENABLE_POSITION_MONITOR = os.getenv("ENABLE_POSITION_MONITOR", "1").lower() in ("1", "true", "yes")
ENABLE_AUTO_PROTECT = os.getenv("ENABLE_AUTO_PROTECT", "1").lower() in ("1", "true", "yes")
POSITION_ALERT_LEVEL = os.getenv("POSITION_ALERT_LEVEL", "critical").lower()
POSITION_PNL_THRESHOLD = float(os.getenv("POSITION_PNL_THRESHOLD_PCT", "10.0"))

# 🎯 TRAILING TP CONFIGURATION
ENABLE_TRAILING_TP = os.getenv("ENABLE_TRAILING_TP", "1").lower() in ("1", "true", "yes")

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
        logger.info("🎯 Trailing TP enabled (config in utils/trailing_tp.py)")
    
    last_report_time = 0
    
    while True:
        current_time = time.time()
        
        # 🎯 TRAILING TP - Managed within ensure_positions_protected (every 30s)
        
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
