"""
🛡️ Ban Shield Monitor Worker
Real-time monitoring and auto-recovery for API rate limiting

Features:
- Monitors shield stats every 10 seconds
- Sends Telegram alerts on zone transitions
- Auto-recovery when load drops
- Comprehensive logging
"""
import os
import sys
import time
import asyncio
import logging
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.ban_shield import get_shield, BanShield
from utils.api_call_tracker import get_tracker, APICallTracker
from utils.telegram_utils import send_telegram_alert

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Configuration
MONITOR_INTERVAL = int(os.getenv('SHIELD_MONITOR_INTERVAL', '10'))  # seconds
ALERT_COOLDOWN = int(os.getenv('SHIELD_ALERT_COOLDOWN', '300'))  # 5 minutes
ENABLED = int(os.getenv('BAN_SHIELD_MONITOR_ENABLE', '1'))

class BanShieldMonitor:
    """
    Monitor and manage API rate limiting shield
    
    Responsibilities:
    - Track shield stats in real-time
    - Send alerts on zone transitions
    - Auto-recover paused workers
    - Log comprehensive metrics
    """
    
    def __init__(self):
        self.shield: BanShield = get_shield()
        self.tracker: APICallTracker = get_tracker()
        
        self.last_alert_time = 0
        self.last_zone = "GREEN"
        self.auto_recovery_triggered = False
        
        logger.info("🛡️ Ban Shield Monitor initialized")
    
    async def send_zone_alert(self, zone: str, stats: dict):
        """Send Telegram alert for zone transition"""
        # Cooldown check
        now = time.time()
        if now - self.last_alert_time < ALERT_COOLDOWN:
            return
        
        self.last_alert_time = now
        
        # Zone emoji
        zone_emoji = {
            "GREEN": "🟢",
            "YELLOW": "🟡",
            "RED": "🔴"
        }.get(zone, "⚪")
        
        # Build message
        rpm = stats['current_rpm']
        max_rpm = stats['max_rpm']
        utilization = stats['utilization_pct']
        
        if zone == "GREEN":
            title = f"{zone_emoji} API Shield: NORMAL"
            message = f"System operating normally"
        elif zone == "YELLOW":
            title = f"{zone_emoji} API Shield: THROTTLING"
            message = f"⚠️ Scanner workers throttled to 50%"
        else:  # RED
            title = f"{zone_emoji} API Shield: CRITICAL"
            message = f"🚨 Non-critical workers PAUSED\n💡 Protecting trades only"
        
        alert = (
            f"{title}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{message}\n\n"
            f"📊 Stats:\n"
            f"  • RPM: {rpm:.1f}/{max_rpm} ({utilization:.1f}%)\n"
            f"  • CRITICAL: {stats['critical_calls_1m']}\n"
            f"  • NORMAL: {stats['normal_calls_1m']}\n"
            f"  • LOW: {stats['low_calls_1m']}\n"
            f"  • Open Positions: {stats['open_positions']}\n"
            f"  • Tokens: {stats['tokens_available']:.1f}\n\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        
        try:
            await send_telegram_alert(alert)
        except Exception as e:
            logger.error(f"Failed to send zone alert: {e}")
    
    async def check_auto_recovery(self):
        """Check if we should resume paused workers"""
        if self.shield.should_auto_recover():
            if not self.auto_recovery_triggered:
                logger.info("✅ Auto-recovery conditions met - resuming workers")
                
                # Send recovery alert
                try:
                    await send_telegram_alert(
                        "🟢 API Shield: AUTO-RECOVERY\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "✅ Load dropped below 25 RPM\n"
                        "🚀 Resuming all workers\n\n"
                        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
                    )
                except Exception as e:
                    logger.error(f"Failed to send recovery alert: {e}")
                
                self.auto_recovery_triggered = True
        else:
            # Reset flag when conditions no longer met
            if self.shield._get_current_rpm() > 30:
                self.auto_recovery_triggered = False
    
    async def monitor_loop(self):
        """Main monitoring loop"""
        logger.info(f"🔄 Starting monitor loop (interval={MONITOR_INTERVAL}s)")
        
        while True:
            try:
                # Get current stats
                stats = self.shield.get_stats()
                current_zone = stats['zone']
                
                # Log stats
                rpm = stats['current_rpm']
                logger.info(
                    f"📊 Shield Stats: Zone={current_zone}, RPM={rpm:.1f}/{stats['max_rpm']}, "
                    f"Tokens={stats['tokens_available']:.1f}, "
                    f"Calls(C={stats['critical_calls_1m']},N={stats['normal_calls_1m']},L={stats['low_calls_1m']})"
                )
                
                # Check zone transition
                if current_zone != self.last_zone:
                    logger.warning(
                        f"🚦 Zone transition: {self.last_zone} → {current_zone}"
                    )
                    await self.send_zone_alert(current_zone, stats)
                    self.last_zone = current_zone
                
                # Check auto-recovery
                await self.check_auto_recovery()
                
                # Get tracker stats
                tracker_stats = self.tracker.get_full_stats(60)
                logger.info(
                    f"📈 Tracker: 1min={tracker_stats['rolling_averages']['rpm_1min']:.1f}, "
                    f"5min={tracker_stats['rolling_averages']['rpm_5min']:.1f}, "
                    f"15min={tracker_stats['rolling_averages']['rpm_15min']:.1f}"
                )
                
                # Log worker breakdown
                worker_breakdown = tracker_stats['worker_breakdown']
                if worker_breakdown:
                    top_workers = sorted(
                        worker_breakdown.items(),
                        key=lambda x: x[1],
                        reverse=True
                    )[:3]
                    logger.info(
                        f"👷 Top workers: " +
                        ", ".join([f"{w}={c}" for w, c in top_workers])
                    )
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}", exc_info=True)
            
            # Wait for next interval
            await asyncio.sleep(MONITOR_INTERVAL)
    
    async def run(self):
        """Run the monitor"""
        if not ENABLED:
            logger.info("⏸️ Ban Shield Monitor disabled (BAN_SHIELD_MONITOR_ENABLE=0)")
            # Keep alive
            while True:
                await asyncio.sleep(60)
            return
        
        logger.info("🚀 Ban Shield Monitor starting...")
        await self.monitor_loop()


async def main():
    """Main entry point"""
    monitor = BanShieldMonitor()
    await monitor.run()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Ban Shield Monitor stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
