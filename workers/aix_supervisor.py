#!/usr/bin/env python3
"""
AI-X (Grok) System Supervisor Worker
Monitors system health, detects anomalies, provides strategic advice using Grok
"""
import os
import sys
import time
import asyncio
import logging
import httpx
from datetime import datetime
from typing import Dict, Any, Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.alerts import send_telegram_message

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("aix_supervisor")

XAI_API_KEY = os.getenv("XAI_API_KEY", "").strip()
XAI_MODEL = os.getenv("XAI_MODEL", "grok-2-latest").strip()
XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
SUPERVISOR_INTERVAL_SEC = int(os.getenv("AIX_SUPERVISOR_INTERVAL", "1800"))
SUPERVISOR_ENABLED = os.getenv("AIX_SUPERVISOR_ENABLED", "1").lower() in ("1", "true", "yes")

_client: Optional[httpx.AsyncClient] = None

def init_xai_client():
    """Initialize X.AI (Grok) HTTP client"""
    global _client
    
    if not XAI_API_KEY:
        logger.warning("XAI_API_KEY not set - supervisor disabled")
        return None
    
    try:
        _client = httpx.AsyncClient(
            base_url=XAI_BASE_URL,
            headers={
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json"
            },
            timeout=60.0
        )
        logger.info(f"AI-X Supervisor initialized with model: {XAI_MODEL}")
        return _client
    except Exception as e:
        logger.error(f"Failed to initialize X.AI client: {e}")
        return None

async def analyze_system_health(system_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Analyze system health and detect anomalies using Grok
    
    Args:
        system_state: Current system metrics and status
        
    Returns:
        Analysis results with anomalies and recommendations
    """
    if not _client:
        return None
    
    try:
        prompt = f"""Analyze this trading system's health and detect any anomalies:

System State:
{system_state}

Provide JSON response with analysis:
{{
  "health_score": <0-100>,
  "anomalies": ["list of detected issues"],
  "recommendations": ["strategic recommendations"],
  "alert_level": "INFO|WARNING|CRITICAL",
  "summary": "<brief analysis>"
}}"""

        messages = [
            {
                "role": "system",
                "content": "You are a system monitoring AI specializing in anomaly detection and strategic supervision. Return ONLY valid JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        response = await _client.post(
            "/chat/completions",
            json={
                "model": XAI_MODEL,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 800
            }
        )
        
        response.raise_for_status()
        data = response.json()
        
        content = data["choices"][0]["message"]["content"].strip()
        
        # Parse JSON response
        import json
        result = json.loads(content)
        
        logger.info(f"Grok analysis: health={result.get('health_score', 0)}%, level={result.get('alert_level', 'INFO')}")
        return result
        
    except Exception as e:
        logger.error(f"Grok health analysis failed: {e}")
        return None

async def get_strategic_advice(context: str) -> Optional[str]:
    """
    Get strategic trading advice from Grok
    
    Args:
        context: Market context and conditions
        
    Returns:
        Strategic advice text
    """
    if not _client:
        return None
    
    try:
        messages = [
            {
                "role": "system",
                "content": "You are a strategic crypto trading advisor. Provide concise, actionable advice."
            },
            {
                "role": "user",
                "content": f"Market Context:\n{context}\n\nProvide strategic trading recommendations."
            }
        ]
        
        response = await _client.post(
            "/chat/completions",
            json={
                "model": XAI_MODEL,
                "messages": messages,
                "temperature": 0.4,
                "max_tokens": 600
            }
        )
        
        response.raise_for_status()
        data = response.json()
        
        return data["choices"][0]["message"]["content"].strip()
        
    except Exception as e:
        logger.error(f"Grok strategic advice failed: {e}")
        return None

async def run_supervisor_cycle():
    """Run supervisor cycle - analyze system and provide insights"""
    try:
        logger.info("Running AI-X supervisor cycle...")
        
        # Mock system state (in production, fetch real metrics)
        system_state = {
            "timestamp": datetime.now().isoformat(),
            "workflows_running": 10,
            "memory_usage_mb": 760,
            "cpu_usage_pct": 45,
            "open_positions": 0,
            "daily_pnl": 0.0,
            "api_health": "OK"
        }
        
        # Analyze health
        analysis = await analyze_system_health(system_state)
        
        if analysis:
            # Send alert if needed
            alert_level = analysis.get("alert_level", "INFO")
            
            if alert_level in ("WARNING", "CRITICAL"):
                await send_supervisor_alert(analysis)
            else:
                logger.info(f"System healthy: {analysis.get('summary', 'OK')}")
        
        logger.info("Supervisor cycle completed")
        
    except Exception as e:
        logger.error(f"Supervisor cycle error: {e}")

async def send_supervisor_alert(analysis: Dict[str, Any]):
    """Send supervisor alert to Telegram"""
    try:
        alert_level = analysis.get("alert_level", "INFO")
        emoji = "⚠️" if alert_level == "WARNING" else "🚨"
        
        anomalies = analysis.get("anomalies", [])
        recommendations = analysis.get("recommendations", [])
        
        msg = f"""{emoji} <b>AI-X Supervisor Alert</b>

⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🎯 <b>Health Score:</b> {analysis.get('health_score', 0)}/100
📊 <b>Alert Level:</b> {alert_level}

<b>Anomalies Detected:</b>
{chr(10).join(f"• {a}" for a in anomalies[:3])}

<b>Recommendations:</b>
{chr(10).join(f"• {r}" for r in recommendations[:3])}

<b>Summary:</b> {analysis.get('summary', 'N/A')}"""

        await send_telegram_message(msg)
        logger.info(f"Supervisor alert sent: {alert_level}")
        
    except Exception as e:
        logger.warning(f"Failed to send supervisor alert: {e}")

async def send_startup_notification():
    """Send supervisor startup notification"""
    try:
        msg = f"""🤖 <b>AI-X (Grok) Supervisor Started</b>

⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🤖 <b>Model:</b> {XAI_MODEL}
✅ <b>Status:</b> Active
🔍 <b>Monitoring system health and anomalies</b>

The supervisor uses Grok AI to detect issues and provide strategic guidance."""

        await send_telegram_message(msg)
        logger.info("Startup notification sent to Telegram")
        
    except Exception as e:
        logger.warning(f"Failed to send startup notification: {e}")

async def main():
    """Main worker loop"""
    if not SUPERVISOR_ENABLED:
        logger.info("AI-X Supervisor is disabled (AIX_SUPERVISOR_ENABLED=0)")
        return
    
    logger.info(f"AI-X Supervisor started (interval: {SUPERVISOR_INTERVAL_SEC}s)")
    
    client = init_xai_client()
    if not client:
        logger.error("X.AI client initialization failed - exiting")
        return
    
    # Send startup notification
    await send_startup_notification()
    
    while True:
        try:
            await run_supervisor_cycle()
            
            # Sleep until next cycle
            logger.info(f"Sleeping for {SUPERVISOR_INTERVAL_SEC} seconds...")
            await asyncio.sleep(SUPERVISOR_INTERVAL_SEC)
            
        except KeyboardInterrupt:
            logger.info("AI-X Supervisor stopped by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error in supervisor loop: {e}")
            await asyncio.sleep(60)  # Short sleep on error

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("AI-X Supervisor shutdown")
