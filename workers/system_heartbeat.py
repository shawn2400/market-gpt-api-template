#!/usr/bin/env python3
# workers/system_heartbeat.py
"""
System Heartbeat Monitor - Periodic health checks and status reports
Monitors system vitals and alerts on issues
"""
import os
import sys
import time
import asyncio
import logging
import httpx
from datetime import datetime, timezone
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.alerts import send_telegram_message

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("system_heartbeat")

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5000").rstrip("/")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "600"))
HEARTBEAT_ENABLED = os.getenv("HEARTBEAT_ENABLED", "1").lower() in ("1", "true", "yes")
ALERT_ON_FAILURE = os.getenv("HEARTBEAT_ALERT_ON_FAILURE", "1").lower() in ("1", "true", "yes")

HEALTH_ENDPOINTS = [
    "/health",
    "/readyz",
    "/api/health"
]

async def check_endpoint(client: httpx.AsyncClient, endpoint: str) -> Dict[str, Any]:
    """Check a single health endpoint"""
    url = f"{BASE_URL}{endpoint}"
    try:
        start = time.time()
        response = await client.get(url, timeout=10.0)
        latency = (time.time() - start) * 1000
        
        return {
            "endpoint": endpoint,
            "status_code": response.status_code,
            "ok": response.status_code == 200,
            "latency_ms": round(latency, 2),
            "response": response.json() if response.status_code == 200 else None
        }
    except httpx.TimeoutException:
        return {
            "endpoint": endpoint,
            "status_code": 0,
            "ok": False,
            "error": "timeout",
            "latency_ms": 10000
        }
    except Exception as e:
        return {
            "endpoint": endpoint,
            "status_code": 0,
            "ok": False,
            "error": str(e),
            "latency_ms": 0
        }

async def get_system_health() -> Dict[str, Any]:
    """Check all health endpoints and return aggregated status"""
    try:
        async with httpx.AsyncClient() as client:
            tasks = [check_endpoint(client, ep) for ep in HEALTH_ENDPOINTS]
            results = await asyncio.gather(*tasks)
        
        all_ok = all(r["ok"] for r in results)
        avg_latency = sum(r["latency_ms"] for r in results if r["ok"]) / len([r for r in results if r["ok"]]) if any(r["ok"] for r in results) else 0
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall_status": "healthy" if all_ok else "degraded",
            "checks": results,
            "avg_latency_ms": round(avg_latency, 2),
            "healthy_count": sum(1 for r in results if r["ok"]),
            "total_count": len(results)
        }
    except Exception as e:
        logger.error(f"Failed to get system health: {e}")
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall_status": "error",
            "error": str(e)
        }

def format_health_message(health: Dict[str, Any]) -> str:
    """Format health data into readable Telegram message"""
    status = health.get("overall_status", "unknown")
    timestamp = health.get("timestamp", "N/A")
    
    status_emoji = "✅" if status == "healthy" else "⚠️" if status == "degraded" else "❌"
    
    lines = [
        f"{status_emoji} <b>System Heartbeat</b>\n",
        f"Status: <b>{status.upper()}</b>",
        f"Time: {timestamp.split('T')[1].split('.')[0]} UTC\n"
    ]
    
    if "checks" in health:
        healthy = health.get("healthy_count", 0)
        total = health.get("total_count", 0)
        lines.append(f"Health Checks: {healthy}/{total} passing")
        
        if health.get("avg_latency_ms"):
            lines.append(f"Avg Latency: {health['avg_latency_ms']:.0f}ms")
        
        lines.append("")
        for check in health["checks"]:
            emoji = "✅" if check["ok"] else "❌"
            endpoint = check["endpoint"]
            if check["ok"]:
                lines.append(f"{emoji} {endpoint} ({check['latency_ms']:.0f}ms)")
            else:
                error = check.get("error", "failed")
                lines.append(f"{emoji} {endpoint} - {error}")
    
    if "error" in health:
        lines.append(f"\n❌ Error: {health['error']}")
    
    return "\n".join(lines)

async def send_heartbeat(health: Dict[str, Any], force: bool = False):
    """Send heartbeat status to Telegram"""
    try:
        status = health.get("overall_status", "unknown")
        
        if not force and status == "healthy" and not ALERT_ON_FAILURE:
            logger.info("System healthy - skipping notification")
            return
        
        message = format_health_message(health)
        
        await send_telegram_message(
            message,
            parse_mode="HTML",
            disable_preview=True
        )
        
        logger.info(f"Heartbeat sent: {status}")
    except Exception as e:
        logger.error(f"Failed to send heartbeat: {e}")

async def heartbeat_cycle(is_first: bool = False):
    """Run one heartbeat check cycle"""
    try:
        logger.info("Running heartbeat check...")
        
        health = await get_system_health()
        
        status = health.get("overall_status", "unknown")
        should_alert = (
            is_first or
            status != "healthy" or
            (ALERT_ON_FAILURE and status == "degraded")
        )
        
        await send_heartbeat(health, force=should_alert)
        
        logger.info(f"Heartbeat cycle completed: {status}")
    except Exception as e:
        logger.error(f"Heartbeat cycle failed: {e}")

async def heartbeat_loop():
    """Main heartbeat monitoring loop"""
    logger.info(f"System Heartbeat Monitor started (interval: {HEARTBEAT_INTERVAL}s)")
    
    if not HEARTBEAT_ENABLED:
        logger.warning("HEARTBEAT_ENABLED=0 - monitor disabled")
        while True:
            await asyncio.sleep(3600)
    
    is_first = True
    while True:
        try:
            await heartbeat_cycle(is_first=is_first)
            is_first = False
            await asyncio.sleep(HEARTBEAT_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Heartbeat monitor stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in heartbeat loop: {e}")
            await asyncio.sleep(60)

def main():
    """Main entry point"""
    try:
        asyncio.run(heartbeat_loop())
    except KeyboardInterrupt:
        logger.info("Heartbeat monitor shutdown")

if __name__ == "__main__":
    main()
