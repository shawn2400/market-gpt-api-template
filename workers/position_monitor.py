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

try:
    from utils.binance_client import init_client as get_client
except:
    from utils.binance_client import _init_client as get_client

try:
    from utils.binance_client import get_all_positions
except:
    def get_all_positions(client):
        return client.futures_position_information() if client else []
from utils.alerts import send_telegram_message

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger("position_monitor")

# Configuration
REPORT_INTERVAL_SEC = int(os.getenv("POSITION_REPORT_INTERVAL_SEC", "1800"))  # 30 minutes
ENABLE_POSITION_MONITOR = os.getenv("ENABLE_POSITION_MONITOR", "1").lower() in ("1", "true", "yes")

def get_active_positions() -> List[Dict[str, Any]]:
    """Get all active positions from Binance"""
    try:
        client = get_client()
        if not client:
            return []
        
        all_positions = get_all_positions(client)
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

async def send_position_report():
    """Send consolidated position report to Telegram"""
    try:
        positions = get_active_positions()
        message = format_position_summary(positions)
        
        await send_telegram_message(
            message,
            parse_mode="HTML",
            disable_preview=True
        )
        
        logger.info(f"Position report sent: {len(positions)} active positions")
    except Exception as e:
        logger.error(f"Failed to send position report: {e}")

async def monitor_loop():
    """Main monitoring loop"""
    logger.info(f"Position Monitor started (interval: {REPORT_INTERVAL_SEC}s)")
    
    while True:
        try:
            await send_position_report()
        except Exception as e:
            logger.error(f"Error in monitor loop: {e}")
        
        # Wait for next interval
        await asyncio.sleep(REPORT_INTERVAL_SEC)

def main():
    if not ENABLE_POSITION_MONITOR:
        logger.info("Position monitor disabled (ENABLE_POSITION_MONITOR=0)")
        return
    
    asyncio.run(monitor_loop())

if __name__ == "__main__":
    main()
