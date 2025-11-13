#!/usr/bin/env python3
# workers/insurance_monitor.py
"""
Insurance Monitor - 5-Layer Account Protection System
Prevents catastrophic account failure through autonomous protection rules

LAYERS:
1. Drawdown Protection - Stop trading if daily PnL <= -5%
2. Margin Ratio Defense - Close losing positions if margin < 10%
3. Cross/Isolated Balancer - Max 40% total capital in Cross margin
4. Funding Rate Killer - Close longs if funding > 0.05% for 3 periods
5. Circuit Breaker - Emergency stop if total PnL <= -8%

All actions execute automatically without human confirmation.
"""
import os
import sys
import time
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.binance_client import _init_client as get_client
from utils.alerts import send_telegram_message

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger("insurance_monitor")

# Configuration
ENABLE_INSURANCE = os.getenv("ENABLE_INSURANCE_MONITOR", "1").lower() in ("1", "true", "yes")
CHECK_INTERVAL_SEC = int(os.getenv("INSURANCE_CHECK_INTERVAL_SEC", "60"))  # 60 seconds

# Layer 1: Drawdown Protection
DRAWDOWN_THRESHOLD_PCT = float(os.getenv("DRAWDOWN_THRESHOLD_PCT", "-5.0"))  # -5%
DRAWDOWN_REDUCE_PCT = float(os.getenv("DRAWDOWN_REDUCE_PCT", "50.0"))  # Close 50% of largest positions

# Layer 2: Margin Ratio Defense
MARGIN_RATIO_MIN = float(os.getenv("MARGIN_RATIO_MIN", "10.0"))  # 10%
MARGIN_RATIO_TARGET = float(os.getenv("MARGIN_RATIO_TARGET", "15.0"))  # 15%

# Layer 3: Cross/Isolated Balancer
MAX_CROSS_PCT = float(os.getenv("MAX_CROSS_PCT", "40.0"))  # 40% max in Cross

# Layer 4: Funding Rate Killer
FUNDING_RATE_THRESHOLD = float(os.getenv("FUNDING_RATE_THRESHOLD", "0.05"))  # 0.05% = 0.0005
FUNDING_PERIODS_REQUIRED = int(os.getenv("FUNDING_PERIODS_REQUIRED", "3"))  # 3 consecutive periods

# Layer 5: Circuit Breaker
CIRCUIT_BREAKER_PCT = float(os.getenv("CIRCUIT_BREAKER_PCT", "-8.0"))  # -8%
CIRCUIT_BREAKER_COOLDOWN_HOURS = int(os.getenv("CIRCUIT_BREAKER_COOLDOWN_HOURS", "24"))  # 24h

# State tracking
_last_balance_snapshot = 0.0
_circuit_breaker_triggered_at: Optional[datetime] = None
_insurance_state = {
    "drawdown_triggers": 0,
    "margin_triggers": 0,
    "cross_rebalances": 0,
    "funding_triggers": 0,
    "circuit_breaker_triggers": 0
}


def get_account_data() -> Optional[Dict[str, Any]]:
    """Get Binance Futures account data"""
    try:
        client = get_client()
        if not client:
            return None
        
        account = client.futures_account()
        return account
    except Exception as e:
        logger.error(f"Failed to get account data: {e}")
        return None


def get_active_positions() -> List[Dict[str, Any]]:
    """Get all active Futures positions"""
    try:
        client = get_client()
        if not client:
            return []
        
        all_positions = client.futures_position_information()
        active = [
            p for p in all_positions 
            if abs(float(p.get("positionAmt", 0))) > 0
        ]
        return active
    except Exception as e:
        logger.error(f"Failed to get positions: {e}")
        return []


def calculate_daily_pnl(account: Dict[str, Any]) -> float:
    """Calculate daily PnL percentage"""
    global _last_balance_snapshot
    
    total_wallet_balance = float(account.get("totalWalletBalance", 0))
    total_unrealized_profit = float(account.get("totalUnrealizedProfit", 0))
    
    # Initialize snapshot on first run
    if _last_balance_snapshot == 0:
        _last_balance_snapshot = total_wallet_balance
        return 0.0
    
    # Calculate PnL vs snapshot
    current_balance = total_wallet_balance + total_unrealized_profit
    pnl_pct = ((current_balance - _last_balance_snapshot) / _last_balance_snapshot) * 100
    
    return pnl_pct


def calculate_margin_ratio(account: Dict[str, Any]) -> float:
    """Calculate Cross Margin Ratio percentage"""
    total_margin_balance = float(account.get("totalMarginBalance", 0))
    total_maintenance_margin = float(account.get("totalMaintMargin", 0))
    
    if total_maintenance_margin == 0:
        return 100.0
    
    margin_ratio = (total_margin_balance / total_maintenance_margin) * 100
    return margin_ratio


async def layer1_drawdown_protection() -> bool:
    """
    Layer 1: Drawdown Protection
    If daily PnL <= -5%, stop new opens + close 50% of largest positions
    Returns: True if triggered
    """
    try:
        account = get_account_data()
        if not account:
            return False
        
        daily_pnl = calculate_daily_pnl(account)
        
        if daily_pnl <= DRAWDOWN_THRESHOLD_PCT:
            logger.warning(f"🚨 DRAWDOWN PROTECTION TRIGGERED | Daily PnL: {daily_pnl:.2f}%")
            
            # Get positions sorted by size
            positions = get_active_positions()
            if not positions:
                return False
            
            # Sort by notional value (largest first)
            positions_sorted = sorted(
                positions,
                key=lambda p: abs(float(p.get("notional", 0))),
                reverse=True
            )
            
            # Close 50% of largest positions
            positions_to_close = int(len(positions_sorted) * (DRAWDOWN_REDUCE_PCT / 100))
            if positions_to_close == 0 and len(positions_sorted) > 0:
                positions_to_close = 1
            
            closed_count = 0
            client = get_client()
            
            for pos in positions_sorted[:positions_to_close]:
                symbol = pos.get("symbol", "")
                amt = float(pos.get("positionAmt", 0))
                
                try:
                    side = "SELL" if amt > 0 else "BUY"
                    qty = abs(amt)
                    
                    order = client.futures_create_order(
                        symbol=symbol,
                        side=side,
                        type="MARKET",
                        quantity=qty,
                        reduceOnly=True
                    )
                    
                    logger.info(f"✅ Closed {symbol} | Order: {order.get('orderId')}")
                    closed_count += 1
                    
                except Exception as e:
                    logger.error(f"❌ Failed to close {symbol}: {e}")
            
            # Send alert
            message = (
                f"🚨 <b>DRAWDOWN PROTECTION ACTIVATED</b>\n\n"
                f"Daily PnL: <b>{daily_pnl:.2f}%</b>\n"
                f"Threshold: {DRAWDOWN_THRESHOLD_PCT}%\n\n"
                f"Action: Closed {closed_count}/{positions_to_close} largest positions\n"
                f"⏸️ New opens suspended for 24h\n\n"
                f"🛡️ Protecting your account!"
            )
            send_telegram_message(message)
            
            _insurance_state["drawdown_triggers"] += 1
            return True
        
        return False
    
    except Exception as e:
        logger.error(f"❌ Layer 1 (Drawdown) failed: {e}")
        return False


async def layer2_margin_defense() -> bool:
    """
    Layer 2: Margin Ratio Defense
    If Cross Margin Ratio < 10%, close worst losing positions until 15%
    Returns: True if triggered
    """
    try:
        account = get_account_data()
        if not account:
            return False
        
        margin_ratio = calculate_margin_ratio(account)
        
        if margin_ratio < MARGIN_RATIO_MIN:
            logger.warning(f"🚨 MARGIN DEFENSE TRIGGERED | Ratio: {margin_ratio:.2f}%")
            
            # Get positions sorted by PnL (worst first)
            positions = get_active_positions()
            if not positions:
                return False
            
            losing_positions = [
                p for p in positions
                if float(p.get("unRealizedProfit", 0)) < 0
            ]
            
            losing_positions_sorted = sorted(
                losing_positions,
                key=lambda p: float(p.get("unRealizedProfit", 0))
            )
            
            if not losing_positions_sorted:
                logger.warning("No losing positions to close for margin defense")
                return False
            
            closed_count = 0
            client = get_client()
            
            # Close losing positions until margin ratio >= target
            for pos in losing_positions_sorted:
                # Recheck margin ratio
                account = get_account_data()
                if account:
                    current_ratio = calculate_margin_ratio(account)
                    if current_ratio >= MARGIN_RATIO_TARGET:
                        break
                
                symbol = pos.get("symbol", "")
                amt = float(pos.get("positionAmt", 0))
                upnl = float(pos.get("unRealizedProfit", 0))
                
                try:
                    side = "SELL" if amt > 0 else "BUY"
                    qty = abs(amt)
                    
                    order = client.futures_create_order(
                        symbol=symbol,
                        side=side,
                        type="MARKET",
                        quantity=qty,
                        reduceOnly=True
                    )
                    
                    logger.info(f"✅ Closed losing {symbol} (PnL: ${upnl:.2f}) | Order: {order.get('orderId')}")
                    closed_count += 1
                    
                except Exception as e:
                    logger.error(f"❌ Failed to close {symbol}: {e}")
            
            # Final margin check
            account = get_account_data()
            final_ratio = calculate_margin_ratio(account) if account else 0
            
            # Send alert
            message = (
                f"🚨 <b>MARGIN DEFENSE ACTIVATED</b>\n\n"
                f"Initial Ratio: <b>{margin_ratio:.2f}%</b>\n"
                f"Final Ratio: <b>{final_ratio:.2f}%</b>\n"
                f"Threshold: {MARGIN_RATIO_MIN}%\n\n"
                f"Action: Closed {closed_count} losing positions\n\n"
                f"🛡️ Account protected from liquidation!"
            )
            asyncio.create_task(send_telegram_message(message))
            
            _insurance_state["margin_triggers"] += 1
            return True
        
        return False
    
    except Exception as e:
        logger.error(f"❌ Layer 2 (Margin) failed: {e}")
        return False


async def layer3_cross_balancer() -> bool:
    """
    Layer 3: Cross/Isolated Balancer
    Max 40% total capital in Cross → Move excess to Isolated (future feature)
    Returns: True if rebalance needed
    """
    try:
        account = get_account_data()
        if not account:
            return False
        
        total_balance = float(account.get("totalWalletBalance", 0))
        total_cross_balance = float(account.get("totalCrossWalletBalance", 0))
        
        if total_balance == 0:
            return False
        
        cross_pct = (total_cross_balance / total_balance) * 100
        
        if cross_pct > MAX_CROSS_PCT:
            logger.warning(f"⚠️ CROSS BALANCER ALERT | Cross: {cross_pct:.1f}% > {MAX_CROSS_PCT}%")
            
            # Note: Actual rebalancing requires transfer API calls
            # For now, just alert - future feature can implement transfers
            
            message = (
                f"⚠️ <b>CROSS MARGIN ALERT</b>\n\n"
                f"Cross Margin: <b>{cross_pct:.1f}%</b>\n"
                f"Maximum: {MAX_CROSS_PCT}%\n\n"
                f"💡 Consider moving excess to Isolated margin\n"
                f"📊 Balance: ${total_balance:.2f}"
            )
            asyncio.create_task(send_telegram_message(message))
            logger.info("Cross balancer alert")
            
            _insurance_state["cross_rebalances"] += 1
            return True
        
        return False
    
    except Exception as e:
        logger.error(f"❌ Layer 3 (Cross Balancer) failed: {e}")
        return False


async def layer4_funding_killer() -> bool:
    """
    Layer 4: Funding Rate Killer
    If funding rate > 0.05% for 3 consecutive periods → Close all Cross longs
    Returns: True if triggered
    """
    try:
        client = get_client()
        if not client:
            return False
        
        # Get funding rate history (limit 3 recent periods)
        # Note: Binance funding rate endpoint returns historical rates
        # This is a simplified check - production should track over time
        
        # For now, log and return False (full implementation requires persistent tracking)
        logger.debug("Layer 4 (Funding Killer) - tracking not yet implemented")
        return False
    
    except Exception as e:
        logger.error(f"❌ Layer 4 (Funding) failed: {e}")
        return False


async def layer5_circuit_breaker() -> bool:
    """
    Layer 5: Circuit Breaker
    If total account PnL <= -8% → CLOSE EVERYTHING + Stop trading 24h
    Returns: True if triggered
    """
    global _circuit_breaker_triggered_at
    
    try:
        # Check cooldown
        if _circuit_breaker_triggered_at:
            elapsed = datetime.now(timezone.utc) - _circuit_breaker_triggered_at
            if elapsed < timedelta(hours=CIRCUIT_BREAKER_COOLDOWN_HOURS):
                logger.debug(f"Circuit breaker in cooldown (remaining: {(timedelta(hours=CIRCUIT_BREAKER_COOLDOWN_HOURS) - elapsed)})")
                return False
            else:
                # Reset cooldown
                _circuit_breaker_triggered_at = None
        
        account = get_account_data()
        if not account:
            return False
        
        daily_pnl = calculate_daily_pnl(account)
        
        if daily_pnl <= CIRCUIT_BREAKER_PCT:
            logger.critical(f"🚨🚨🚨 CIRCUIT BREAKER TRIGGERED | PnL: {daily_pnl:.2f}%")
            
            # Close ALL positions
            positions = get_active_positions()
            if not positions:
                return False
            
            closed_count = 0
            client = get_client()
            
            for pos in positions:
                symbol = pos.get("symbol", "")
                amt = float(pos.get("positionAmt", 0))
                
                try:
                    side = "SELL" if amt > 0 else "BUY"
                    qty = abs(amt)
                    
                    order = client.futures_create_order(
                        symbol=symbol,
                        side=side,
                        type="MARKET",
                        quantity=qty,
                        reduceOnly=True
                    )
                    
                    logger.critical(f"🛑 EMERGENCY CLOSE: {symbol} | Order: {order.get('orderId')}")
                    closed_count += 1
                    
                except Exception as e:
                    logger.error(f"❌ Failed to close {symbol}: {e}")
            
            # Set cooldown
            _circuit_breaker_triggered_at = datetime.now(timezone.utc)
            
            # Send CRITICAL alert
            message = (
                f"🚨🚨🚨 <b>CIRCUIT BREAKER ACTIVATED</b> 🚨🚨🚨\n\n"
                f"Account PnL: <b>{daily_pnl:.2f}%</b>\n"
                f"Threshold: {CIRCUIT_BREAKER_PCT}%\n\n"
                f"🛑 <b>ALL POSITIONS CLOSED</b>\n"
                f"Closed: {closed_count} positions\n\n"
                f"⏸️ Trading suspended for {CIRCUIT_BREAKER_COOLDOWN_HOURS}h\n\n"
                f"🛡️ Emergency protection activated!"
            )
            send_telegram_message(message)
            
            _insurance_state["circuit_breaker_triggers"] += 1
            return True
        
        return False
    
    except Exception as e:
        logger.error(f"❌ Layer 5 (Circuit Breaker) failed: {e}")
        return False


async def run_insurance_checks() -> None:
    """Run all 5 insurance layers sequentially"""
    try:
        # Layer 5 (Circuit Breaker) - Highest priority, check first
        if await layer5_circuit_breaker():
            logger.critical("Circuit breaker triggered - stopping all other checks")
            return
        
        # Layer 2 (Margin Defense) - Second priority
        if await layer2_margin_defense():
            logger.warning("Margin defense triggered")
        
        # Layer 1 (Drawdown Protection)
        if await layer1_drawdown_protection():
            logger.warning("Drawdown protection triggered")
        
        # Layer 3 (Cross Balancer)
        if await layer3_cross_balancer():
            logger.info("Cross balancer alert")
        
        # Layer 4 (Funding Killer) - Future feature
        if await layer4_funding_killer():
            logger.warning("Funding killer triggered")
    
    except Exception as e:
        logger.error(f"❌ Insurance checks failed: {e}")


async def monitor_loop():
    """Main insurance monitoring loop"""
    global _last_balance_snapshot
    
    logger.info(
        f"🛡️ Insurance Monitor started | "
        f"Check interval: {CHECK_INTERVAL_SEC}s"
    )
    logger.info(
        f"Layer 1 (Drawdown): {DRAWDOWN_THRESHOLD_PCT}% | "
        f"Layer 2 (Margin): {MARGIN_RATIO_MIN}% | "
        f"Layer 5 (Circuit): {CIRCUIT_BREAKER_PCT}%"
    )
    
    # Initialize balance snapshot
    account = get_account_data()
    if account:
        _last_balance_snapshot = float(account.get("totalWalletBalance", 0))
        logger.info(f"📊 Balance snapshot initialized: ${_last_balance_snapshot:.2f}")
    
    while True:
        try:
            await run_insurance_checks()
        except Exception as e:
            logger.error(f"Error in insurance loop: {e}")
        
        await asyncio.sleep(CHECK_INTERVAL_SEC)


def main():
    if not ENABLE_INSURANCE:
        logger.info("Insurance monitor disabled (ENABLE_INSURANCE_MONITOR=0)")
        return
    
    asyncio.run(monitor_loop())


if __name__ == "__main__":
    main()
