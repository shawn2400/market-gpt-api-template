#!/usr/bin/env python3
# workers/gpt5_orchestrator.py
"""
GPT-5 Central Brain - Coordinates AI decision-making across the system
Uses GPT-5 (gpt-5-2025-08-07) for high-level trading orchestration
"""
import os
import sys
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    AsyncOpenAI = None

from utils.alerts import send_telegram_message

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("gpt5_orchestrator")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GPT5_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-2025-08-07").strip()
ORCHESTRATOR_INTERVAL_SEC = int(os.getenv("ORCHESTRATOR_INTERVAL_SEC", "1800"))
ORCHESTRATOR_ENABLED = os.getenv("GPT5_ORCHESTRATOR_ENABLED", "1").lower() in ("1", "true", "yes")

_client: Optional[Any] = None

def init_openai_client():
    """Initialize OpenAI client for GPT-5"""
    global _client
    
    if not OPENAI_AVAILABLE:
        logger.warning("OpenAI SDK not available - orchestrator running in monitoring-only mode")
        return None
    
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set - orchestrator disabled")
        return None
    
    try:
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        logger.info(f"GPT-5 orchestrator initialized with model: {GPT5_MODEL}")
        return _client
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        return None

async def analyze_system_state() -> Dict[str, Any]:
    """Analyze current system state and market conditions"""
    try:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "operational",
            "analysis_available": bool(_client),
            "model": GPT5_MODEL
        }
    except Exception as e:
        logger.error(f"Failed to analyze system state: {e}")
        return {"status": "error", "error": str(e)}

async def get_gpt5_recommendation(context: str) -> Optional[str]:
    """Get strategic recommendation from GPT-5"""
    if not _client:
        return None
    
    try:
        messages = [
            {
                "role": "system",
                "content": "You are an expert cryptocurrency trading strategist. Provide concise, actionable recommendations based on system state and market conditions."
            },
            {
                "role": "user",
                "content": f"System State:\n{context}\n\nProvide strategic trading recommendations for the next period."
            }
        ]
        
        response = await _client.chat.completions.create(
            model=GPT5_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=500
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"GPT-5 recommendation failed: {e}")
        return None

async def send_orchestrator_update(analysis: Dict[str, Any], recommendation: Optional[str]):
    """Send orchestrator update to Telegram"""
    try:
        lines = [
            "🧠 <b>GPT-5 Central Brain Update</b>\n",
            f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"🤖 Model: <code>{GPT5_MODEL}</code>",
            f"📊 Status: {analysis.get('status', 'unknown')}\n"
        ]
        
        if recommendation:
            lines.append("<b>Strategic Recommendation:</b>")
            lines.append(f"<i>{recommendation}</i>")
        else:
            lines.append("⚠️ No recommendation available (running in monitoring mode)")
        
        message = "\n".join(lines)
        
        await send_telegram_message(
            message,
            parse_mode="HTML",
            disable_preview=True
        )
        
        logger.info("Orchestrator update sent to Telegram")
    except Exception as e:
        logger.error(f"Failed to send orchestrator update: {e}")

async def orchestrator_cycle():
    """Run one orchestrator analysis cycle"""
    try:
        logger.info("Running GPT-5 orchestrator cycle...")
        
        analysis = await analyze_system_state()
        
        context = f"Timestamp: {analysis['timestamp']}\nStatus: {analysis['status']}"
        recommendation = await get_gpt5_recommendation(context) if _client else None
        
        await send_orchestrator_update(analysis, recommendation)
        
        logger.info("Orchestrator cycle completed")
    except Exception as e:
        logger.error(f"Orchestrator cycle failed: {e}")

async def orchestrator_loop():
    """Main orchestrator loop"""
    logger.info(f"GPT-5 Central Brain started (interval: {ORCHESTRATOR_INTERVAL_SEC}s)")
    
    if not ORCHESTRATOR_ENABLED:
        logger.warning("GPT5_ORCHESTRATOR_ENABLED=0 - orchestrator disabled")
        while True:
            await asyncio.sleep(3600)
    
    init_openai_client()
    
    while True:
        try:
            await orchestrator_cycle()
            await asyncio.sleep(ORCHESTRATOR_INTERVAL_SEC)
        except KeyboardInterrupt:
            logger.info("GPT-5 orchestrator stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in orchestrator loop: {e}")
            await asyncio.sleep(60)

def main():
    """Main entry point"""
    try:
        asyncio.run(orchestrator_loop())
    except KeyboardInterrupt:
        logger.info("GPT-5 orchestrator shutdown")

if __name__ == "__main__":
    main()
