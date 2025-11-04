#!/usr/bin/env python3
"""
DeepSeek Trade Optimizer Worker
Analyzes trade proposals and optimizes entry/TP/SL parameters using DeepSeek AI
"""
import os
import sys
import time
import asyncio
import logging
import httpx
from datetime import datetime
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.alerts import send_telegram_message

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("deepseek_optimizer")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
OPTIMIZER_INTERVAL_SEC = int(os.getenv("DEEPSEEK_OPTIMIZER_INTERVAL", "3600"))
OPTIMIZER_ENABLED = os.getenv("DEEPSEEK_OPTIMIZER_ENABLED", "1").lower() in ("1", "true", "yes")

_client: Optional[httpx.AsyncClient] = None

def init_deepseek_client():
    """Initialize DeepSeek HTTP client"""
    global _client
    
    if not DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY not set - optimizer disabled")
        return None
    
    try:
        _client = httpx.AsyncClient(
            base_url=DEEPSEEK_BASE_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            timeout=60.0
        )
        logger.info(f"DeepSeek optimizer initialized with model: {DEEPSEEK_MODEL}")
        return _client
    except Exception as e:
        logger.error(f"Failed to initialize DeepSeek client: {e}")
        return None

async def optimize_trade_parameters(trade_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Optimize trade parameters using DeepSeek AI
    
    Args:
        trade_data: Trade proposal with symbol, entry, TP, SL, etc.
        
    Returns:
        Optimized parameters or None on failure
    """
    if not _client:
        return None
    
    try:
        prompt = f"""Analyze this crypto futures trade proposal and suggest optimizations:

Symbol: {trade_data.get('symbol')}
Side: {trade_data.get('side')}
Entry: ${trade_data.get('entry', 0):.4f}
Take Profit: ${trade_data.get('tp', 0):.4f}
Stop Loss: ${trade_data.get('sl', 0):.4f}
Risk/Reward: {trade_data.get('rr', 0):.2f}
Leverage: {trade_data.get('leverage', 1)}x

Market Context:
{trade_data.get('context', 'N/A')}

Provide JSON response with optimized parameters:
{{
  "optimized_entry": <price>,
  "optimized_tp": <price>,
  "optimized_sl": <price>,
  "optimized_leverage": <1-10>,
  "confidence": <0-100>,
  "reasoning": "<brief explanation>"
}}"""

        messages = [
            {
                "role": "system",
                "content": "You are an expert crypto trader specializing in parameter optimization. Return ONLY valid JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        response = await _client.post(
            "/chat/completions",
            json={
                "model": DEEPSEEK_MODEL,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 500
            }
        )
        
        response.raise_for_status()
        data = response.json()
        
        content = data["choices"][0]["message"]["content"].strip()
        
        # Parse JSON response
        import json
        result = json.loads(content)
        
        logger.info(f"DeepSeek optimization: {trade_data.get('symbol')} confidence={result.get('confidence', 0)}%")
        return result
        
    except Exception as e:
        logger.error(f"DeepSeek optimization failed: {e}")
        return None

async def run_optimizer_cycle():
    """Run optimizer cycle - analyze pending trades"""
    try:
        logger.info("Running DeepSeek optimizer cycle...")
        
        # In production, fetch pending trades from API/database
        # For now, just log that we're ready
        
        logger.info("DeepSeek optimizer ready for trade optimization requests")
        
    except Exception as e:
        logger.error(f"Optimizer cycle error: {e}")

async def send_optimizer_status():
    """Send optimizer status to Telegram"""
    try:
        status_msg = f"""🤖 <b>DeepSeek Optimizer Status</b>

⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🤖 <b>Model:</b> {DEEPSEEK_MODEL}
✅ <b>Status:</b> Active
📊 <b>Ready to optimize trades</b>

The optimizer analyzes entry points, TP/SL levels, and position sizing for maximum profitability."""

        await send_telegram_message(status_msg)
        logger.info("Optimizer status sent to Telegram")
        
    except Exception as e:
        logger.warning(f"Failed to send optimizer status: {e}")

async def main():
    """Main worker loop"""
    if not OPTIMIZER_ENABLED:
        logger.info("DeepSeek Optimizer is disabled (DEEPSEEK_OPTIMIZER_ENABLED=0)")
        return
    
    logger.info(f"DeepSeek Optimizer started (interval: {OPTIMIZER_INTERVAL_SEC}s)")
    
    client = init_deepseek_client()
    if not client:
        logger.error("DeepSeek client initialization failed - exiting")
        return
    
    # Send startup notification
    await send_optimizer_status()
    
    while True:
        try:
            await run_optimizer_cycle()
            
            # Sleep until next cycle
            logger.info(f"Sleeping for {OPTIMIZER_INTERVAL_SEC} seconds...")
            await asyncio.sleep(OPTIMIZER_INTERVAL_SEC)
            
        except KeyboardInterrupt:
            logger.info("DeepSeek Optimizer stopped by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error in optimizer loop: {e}")
            await asyncio.sleep(60)  # Short sleep on error

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("DeepSeek Optimizer shutdown")
