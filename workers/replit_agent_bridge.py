#!/usr/bin/env python3
# workers/replit_agent_bridge.py
"""
Replit Agent Bridge - Integration layer for Replit Agent collaboration
Enables AI-assisted development and automated system improvements
"""
import os
import sys
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.alerts import send_telegram_message

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("replit_agent_bridge")

REPLIT_AGENT_ENABLED = os.getenv("REPLIT_AGENT_ENABLED", "1").lower() in ("1", "true", "yes")
BRIDGE_INTERVAL_SEC = int(os.getenv("REPLIT_BRIDGE_INTERVAL_SEC", "3600"))
REPLIT_ENVIRONMENT = os.getenv("REPL_SLUG") is not None

async def check_replit_environment() -> Dict[str, Any]:
    """Check if running in Replit environment and gather context"""
    try:
        env_vars = {
            "repl_slug": os.getenv("REPL_SLUG"),
            "repl_owner": os.getenv("REPL_OWNER"),
            "repl_id": os.getenv("REPL_ID"),
            "replit_domains": os.getenv("REPLIT_DOMAINS"),
            "is_replit": REPLIT_ENVIRONMENT
        }
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "environment": "replit" if REPLIT_ENVIRONMENT else "other",
            "details": env_vars,
            "bridge_active": REPLIT_AGENT_ENABLED
        }
    except Exception as e:
        logger.error(f"Failed to check environment: {e}")
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "environment": "unknown",
            "error": str(e)
        }

async def monitor_system_improvements() -> Dict[str, Any]:
    """Monitor for potential system improvements and optimization opportunities"""
    try:
        improvements = []
        
        if not os.path.exists("logs/app.log"):
            improvements.append({
                "category": "logging",
                "suggestion": "Consider implementing structured logging to logs/app.log",
                "priority": "low"
            })
        
        if not os.path.exists(".git"):
            improvements.append({
                "category": "version_control",
                "suggestion": "Initialize git repository for version tracking",
                "priority": "medium"
            })
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "improvements_found": len(improvements),
            "suggestions": improvements
        }
    except Exception as e:
        logger.error(f"Failed to monitor improvements: {e}")
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }

def format_bridge_message(env_check: Dict[str, Any], improvements: Dict[str, Any]) -> str:
    """Format bridge status into readable message"""
    lines = [
        "🤝 <b>Replit Agent Bridge Status</b>\n",
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"🌐 Environment: <code>{env_check.get('environment', 'unknown')}</code>",
        f"🔗 Bridge: {'Active' if REPLIT_AGENT_ENABLED else 'Inactive'}\n"
    ]
    
    if env_check.get("environment") == "replit":
        details = env_check.get("details", {})
        if details.get("repl_slug"):
            lines.append(f"📦 Repl: <code>{details['repl_slug']}</code>")
    
    improvement_count = improvements.get("improvements_found", 0)
    if improvement_count > 0:
        lines.append(f"\n💡 Optimization Opportunities: {improvement_count}")
        for suggestion in improvements.get("suggestions", [])[:3]:
            priority = suggestion.get("priority", "low")
            emoji = "🔴" if priority == "high" else "🟡" if priority == "medium" else "🟢"
            lines.append(f"{emoji} {suggestion.get('category', 'general')}: {suggestion.get('suggestion', 'N/A')}")
    else:
        lines.append("\n✅ No immediate optimization suggestions")
    
    return "\n".join(lines)

async def send_bridge_update(env_check: Dict[str, Any], improvements: Dict[str, Any]):
    """Send bridge status update to Telegram"""
    try:
        message = format_bridge_message(env_check, improvements)
        
        await send_telegram_message(
            message,
            parse_mode="HTML",
            disable_preview=True
        )
        
        logger.info("Bridge update sent to Telegram")
    except Exception as e:
        logger.error(f"Failed to send bridge update: {e}")

async def bridge_cycle():
    """Run one bridge monitoring cycle"""
    try:
        logger.info("Running Replit Agent Bridge cycle...")
        
        env_check = await check_replit_environment()
        improvements = await monitor_system_improvements()
        
        await send_bridge_update(env_check, improvements)
        
        logger.info("Bridge cycle completed")
    except Exception as e:
        logger.error(f"Bridge cycle failed: {e}")

async def bridge_loop():
    """Main bridge monitoring loop"""
    logger.info(f"Replit Agent Bridge started (interval: {BRIDGE_INTERVAL_SEC}s)")
    
    if not REPLIT_AGENT_ENABLED:
        logger.warning("REPLIT_AGENT_ENABLED=0 - bridge disabled")
        while True:
            await asyncio.sleep(3600)
    
    while True:
        try:
            await bridge_cycle()
            await asyncio.sleep(BRIDGE_INTERVAL_SEC)
        except KeyboardInterrupt:
            logger.info("Replit Agent Bridge stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in bridge loop: {e}")
            await asyncio.sleep(60)

def main():
    """Main entry point"""
    try:
        asyncio.run(bridge_loop())
    except KeyboardInterrupt:
        logger.info("Replit Agent Bridge shutdown")

if __name__ == "__main__":
    main()
