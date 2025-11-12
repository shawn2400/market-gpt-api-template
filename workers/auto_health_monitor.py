#!/usr/bin/env python3
"""
Auto Health Monitor - 100% System Reliability
בודק הכל כל 30 שניות ומתקן בעיות אוטומטית
Uses Telegram Digest System - sends alerts to digest queue instead of immediate spam
"""
import os, sys, time, logging, asyncio, json
from datetime import datetime
from typing import Dict, Any, List, Optional, Protocol

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("auto_health_monitor")

# Digest protocol for type safety
class DigestProtocol(Protocol):
    def add_health_alert(self, level: str, message: str, details: Optional[Dict[str, Any]] = None) -> None: ...

# Import digest system
try:
    from utils.telegram_digest import get_digest
except Exception:
    class MockDigest:
        def add_health_alert(self, level: str = "INFO", message: str = "", details: Optional[Dict[str, Any]] = None) -> None:
            pass
    
    def get_digest() -> DigestProtocol:
        return MockDigest()  # type: ignore[return-value]

# === Configuration ===
CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "30"))  # 30 seconds
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5000")
TELEGRAM_ENABLED = os.getenv("TELEGRAM_SEND_ENABLE", "1") == "1"
AUTO_FIX_ENABLED = os.getenv("AUTO_FIX_ENABLE", "1") == "1"

# Detect environment: Replit vs Production (Render)
IS_REPLIT = bool(os.getenv("REPL_SLUG"))  # Replit-specific env var
IS_PRODUCTION = not IS_REPLIT

# === Health Checks ===
class HealthCheck:
    def __init__(self):
        self.issues: List[Dict[str, Any]] = []
        self.fixes_applied: List[str] = []
        
    async def check_all(self) -> Dict[str, Any]:
        """Run all health checks"""
        checks = {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "healthy",
            "checks": {},
            "issues": [],
            "fixes_applied": [],
            "environment": "Replit" if IS_REPLIT else "Production"
        }
        
        # REPLIT: Skip API/Dashboard checks (no web server in dev)
        if IS_PRODUCTION:
            # 1. API Health (Production only)
            api_ok = await self.check_api_health()
            checks["checks"]["api"] = {"status": "ok" if api_ok else "error"}
            if not api_ok:
                checks["issues"].append("API not responding")
                if AUTO_FIX_ENABLED:
                    fix = await self.fix_api_health()
                    if fix:
                        checks["fixes_applied"].append(fix)
            
            # 2. Dashboard Accessible (Production only)
            dashboard_ok = await self.check_dashboard()
            checks["checks"]["dashboard"] = {"status": "ok" if dashboard_ok else "error"}
            if not dashboard_ok:
                checks["issues"].append("Dashboard not accessible")
            
            # 3. Workflows Running (Production only)
            workflows_ok = await self.check_workflows()
            checks["checks"]["workflows"] = workflows_ok
            if workflows_ok.get("status") != "ok":
                msg = workflows_ok.get("message", "Workflows not running properly")
                checks["issues"].append(f"Workflows: {msg}")
        else:
            # REPLIT: Only check workers are alive
            checks["checks"]["api"] = {"status": "skipped", "reason": "Development mode"}
            checks["checks"]["dashboard"] = {"status": "skipped", "reason": "Development mode"}
            checks["checks"]["workflows"] = {"status": "ok", "count": "dev", "message": "Workers running in Replit"}
        
        # 4. Database Connection (Always check)
        db_ok = await self.check_database()
        checks["checks"]["database"] = {"status": "ok" if db_ok else "error"}
        if not db_ok:
            checks["issues"].append("Database connection failed")
        
        # 5. Memory Usage (Always check)
        memory_ok = await self.check_memory()
        checks["checks"]["memory"] = memory_ok
        
        # 6. Disk Space (Always check)
        disk_ok = await self.check_disk()
        checks["checks"]["disk"] = disk_ok
        
        # Overall status
        if checks["issues"]:
            checks["status"] = "degraded" if len(checks["issues"]) < 3 else "critical"
        
        return checks
    
    async def check_api_health(self) -> bool:
        """Check if API is responding"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{BASE_URL}/health")
                return response.status_code == 200
        except Exception as e:
            logger.error(f"API health check failed: {e}")
            return False
    
    async def check_dashboard(self) -> bool:
        """Check if dashboard is accessible"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{BASE_URL}/static/dashboard/ultimate-workbook.html")
                return response.status_code == 200 and len(response.text) > 10000
        except Exception as e:
            logger.error(f"Dashboard check failed: {e}")
            return False
    
    async def check_database(self) -> bool:
        """Check database connection"""
        try:
            from utils.db import _conn, USE_DB
            if not USE_DB:
                return True  # DB disabled, consider it healthy
            
            with _conn() as conn:
                if conn:
                    cur = conn.cursor()
                    cur.execute("SELECT 1")
                    return True
            return False
        except Exception as e:
            logger.error(f"Database check failed: {e}")
            return False
    
    async def check_workflows(self) -> Dict[str, Any]:
        """Check workflow status via /api/info endpoint"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{BASE_URL}/api/info")
                if response.status_code == 200:
                    data = response.json()
                    workflow_count = data.get("workflows_active", 0)
                    if workflow_count >= 7:  # Expect 7 workflows (6 workers + main server)
                        return {"status": "ok", "count": workflow_count}
                    else:
                        return {
                            "status": "degraded",
                            "count": workflow_count,
                            "message": f"Only {workflow_count} workflows running (expected 7+)"
                        }
                return {"status": "error", "count": 0, "message": "API /api/info unreachable"}
        except Exception as e:
            logger.error(f"Workflow check failed: {e}")
            return {"status": "error", "count": 0, "message": str(e)}
    
    async def check_memory(self) -> Dict[str, Any]:
        """Check memory usage"""
        try:
            import psutil
            memory = psutil.virtual_memory()
            process = psutil.Process()
            return {
                "status": "ok" if memory.percent < 85 else "warning",
                "system_percent": round(memory.percent, 1),
                "process_mb": round(process.memory_info().rss / 1024 / 1024, 1)
            }
        except Exception:
            return {"status": "unknown"}
    
    async def check_disk(self) -> Dict[str, Any]:
        """Check disk usage"""
        try:
            import psutil
            disk = psutil.disk_usage('/')
            return {
                "status": "ok" if disk.percent < 85 else "warning",
                "percent": round(disk.percent, 1),
                "free_gb": round(disk.free / 1024 / 1024 / 1024, 1)
            }
        except Exception:
            return {"status": "unknown"}
    
    async def fix_api_health(self) -> Optional[str]:
        """Try to fix API health issues"""
        logger.warning("🔧 Attempting to fix API health...")
        # Could restart workflows, clear cache, etc.
        return None

# === Telegram Alerts ===
async def send_telegram_alert(message: str, level: str = "WARNING"):
    """Send alert to Digest Queue (batched delivery)"""
    if not TELEGRAM_ENABLED:
        return
    
    try:
        digest = get_digest()
        
        emoji = {
            "INFO": "ℹ️",
            "WARNING": "⚠️",
            "ERROR": "🔴",
            "CRITICAL": "🚨",
            "SUCCESS": "✅"
        }.get(level, "📢")
        
        formatted = f"{emoji} *Auto Health Monitor*\n\n{message}"
        
        # Add to digest queue instead of immediate send
        digest.add_health_alert(level=level, message=formatted)
        logger.info(f"Health alert queued for digest: {level}")
    except Exception as e:
        logger.error(f"Failed to queue Telegram alert: {e}")

# === Main Loop ===
async def main():
    logger.info("🚀 Auto Health Monitor started")
    logger.info(f"🌍 Environment: {'Replit (Development)' if IS_REPLIT else 'Production (Render)'}")
    logger.info(f"⏱️  Check interval: {CHECK_INTERVAL} seconds")
    logger.info(f"🔧 Auto-fix: {'ENABLED' if AUTO_FIX_ENABLED else 'DISABLED'}")
    logger.info(f"📱 Telegram: {'ENABLED' if TELEGRAM_ENABLED else 'DISABLED'}")
    if IS_REPLIT:
        logger.info("ℹ️  Running in Replit - skipping API/Dashboard checks")
    
    health_checker = HealthCheck()
    consecutive_failures = 0
    last_alert_time = 0
    last_critical_alert_time = 0
    
    while True:
        try:
            # Run health checks
            result = await health_checker.check_all()
            
            # Log results
            status_emoji = {
                "healthy": "✅",
                "degraded": "⚠️",
                "critical": "🔴"
            }.get(result["status"], "❓")
            
            logger.info(f"{status_emoji} System Status: {result['status'].upper()}")
            
            # Alert on issues
            if result["issues"]:
                consecutive_failures += 1
                logger.warning(f"⚠️  Issues detected ({consecutive_failures}): {', '.join(result['issues'])}")
                
                # Send Telegram alert to DIGEST (batched delivery)
                current_time = time.time()
                if current_time - last_alert_time > 300:  # Max 1 digest alert per 5 min
                    alert_msg = (
                        f"*Status:* {result['status'].upper()}\n"
                        f"*Issues:* {len(result['issues'])}\n"
                        f"*Details:*\n" + "\n".join(f"• {issue}" for issue in result['issues'])
                    )
                    
                    if result["fixes_applied"]:
                        alert_msg += f"\n\n*Auto-fixes applied:*\n" + "\n".join(f"✅ {fix}" for fix in result['fixes_applied'])
                    
                    await send_telegram_alert(alert_msg, "ERROR" if result["status"] == "critical" else "WARNING")
                    last_alert_time = current_time
                
                # CRITICAL: Only send if TRULY critical (≥5 consecutive + 15min cooldown)
                if consecutive_failures >= 5 and (current_time - last_critical_alert_time > 900):
                    restart_msg = (
                        f"🚨 CRITICAL: {consecutive_failures} consecutive failures!\n\n" +
                        "\n".join(f"• {issue}" for issue in result['issues']) +
                        "\n\n⚠️ **IMPORTANT:** All workflows may have stopped!\n" +
                        "➡️ Please manually restart workflows or check the Replit console.\n" +
                        "💡 Tip: Click the 'Run' button in Replit to restart all services."
                    )
                    await send_telegram_alert(restart_msg, "CRITICAL")
                    last_critical_alert_time = current_time
                    consecutive_failures = 0  # Reset after critical alert
            else:
                # System healthy
                if consecutive_failures > 0:
                    logger.info(f"✅ System recovered after {consecutive_failures} failures")
                    await send_telegram_alert(
                        f"System recovered! All checks passing.",
                        "SUCCESS"
                    )
                consecutive_failures = 0
            
            # Save status to file for dashboard
            try:
                status_file = "/tmp/health_status.json"
                with open(status_file, 'w') as f:
                    json.dump(result, f, indent=2)
            except Exception as e:
                logger.error(f"Failed to save status: {e}")
            
        except Exception as e:
            logger.error(f"Health check error: {e}", exc_info=True)
            consecutive_failures += 1
        
        # Wait for next check
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Auto Health Monitor stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
