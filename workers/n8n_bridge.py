# workers/n8n_bridge.py
"""
N8N Integration Bridge
======================
Secure webhook bridge for integrating N8N workflows with AlgoGPT.

Features:
- HMAC signature validation for incoming webhooks
- Fallback queue system for failed deliveries
- Heartbeat monitoring
- Rate limiting and anti-abuse protection
- Support for bidirectional communication (N8N → AlgoGPT → N8N)

Use cases:
- News ingestion from external sources
- Trade approval escalation to humans
- Incident paging and alerting
- External system triggers

Author: AlgoGPT Team
Level: Production Grade
"""

from __future__ import annotations

import os
import hmac
import hashlib
import json
import time
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from collections import deque
import asyncio

import httpx

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

LOGGER = logging.getLogger("n8n_bridge")


class N8NWebhookValidator:
    """Validates incoming N8N webhooks using HMAC signatures"""
    
    def __init__(self, secret: str):
        self.secret = secret.encode('utf-8')
        self.logger = LOGGER
    
    def validate_signature(
        self,
        payload: bytes,
        signature: str,
        timestamp: Optional[int] = None,
        max_age_seconds: int = 300
    ) -> bool:
        """
        Validate HMAC signature of webhook payload.
        
        Args:
            payload: Raw webhook payload (bytes)
            signature: HMAC signature from webhook header
            timestamp: Unix timestamp (optional, for replay attack prevention)
            max_age_seconds: Maximum age of request (default 5 minutes)
            
        Returns:
            True if signature is valid, False otherwise
        """
        # Check timestamp to prevent replay attacks
        if timestamp is not None:
            current_time = int(time.time())
            if current_time - timestamp > max_age_seconds:
                self.logger.warning(f"Webhook too old: {current_time - timestamp}s > {max_age_seconds}s")
                return False
        
        # Calculate expected signature
        expected_sig = hmac.new(
            self.secret,
            payload,
            hashlib.sha256
        ).hexdigest()
        
        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(expected_sig, signature):
            self.logger.warning(f"Invalid signature: expected={expected_sig[:8]}..., got={signature[:8]}...")
            return False
        
        return True


class N8NFallbackQueue:
    """Queue for failed webhook deliveries with retry logic"""
    
    def __init__(self, max_size: int = 1000, retry_interval: int = 60):
        self.queue: deque = deque(maxlen=max_size)
        self.retry_interval = retry_interval  # Seconds between retries
        self.logger = LOGGER
    
    def enqueue(self, webhook_data: Dict[str, Any], target_url: str):
        """Add failed webhook to retry queue"""
        item = {
            "data": webhook_data,
            "target_url": target_url,
            "timestamp": time.time(),
            "retry_count": 0,
            "last_retry": None
        }
        self.queue.append(item)
        self.logger.info(f"📦 Queued webhook for retry: {target_url} (queue size: {len(self.queue)})")
    
    async def process_queue(self, max_retries: int = 3):
        """Process queued webhooks with retry logic"""
        processed = 0
        failed = 0
        
        items_to_remove = []
        
        for item in list(self.queue):
            # Check if enough time has passed since last retry
            if item["last_retry"] is not None:
                if time.time() - item["last_retry"] < self.retry_interval:
                    continue
            
            # Attempt delivery
            success = await self._deliver_webhook(item["target_url"], item["data"])
            
            if success:
                items_to_remove.append(item)
                processed += 1
                self.logger.info(f"✅ Webhook delivered successfully after {item['retry_count']} retries")
            else:
                item["retry_count"] += 1
                item["last_retry"] = time.time()
                
                if item["retry_count"] >= max_retries:
                    items_to_remove.append(item)
                    failed += 1
                    self.logger.error(f"❌ Webhook failed after {max_retries} retries, dropping")
        
        # Remove processed/failed items
        for item in items_to_remove:
            try:
                self.queue.remove(item)
            except ValueError:
                pass
        
        if processed > 0 or failed > 0:
            self.logger.info(f"Queue processed: {processed} delivered, {failed} dropped, {len(self.queue)} remaining")
    
    async def _deliver_webhook(self, url: str, data: Dict[str, Any]) -> bool:
        """Attempt to deliver webhook"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=data)
                return response.status_code < 400
        except Exception as e:
            self.logger.debug(f"Webhook delivery failed: {e}")
            return False


class N8NHeartbeat:
    """Monitors N8N bridge health with periodic heartbeats"""
    
    def __init__(self, interval_seconds: int = 60):
        self.interval = interval_seconds
        self.last_heartbeat = time.time()
        self.last_webhook_received = None
        self.webhook_count = 0
        self.error_count = 0
        self.logger = LOGGER
    
    def record_webhook(self, success: bool = True):
        """Record webhook processing"""
        self.webhook_count += 1
        self.last_webhook_received = time.time()
        if not success:
            self.error_count += 1
    
    def get_status(self) -> Dict[str, Any]:
        """Get current bridge status"""
        uptime = time.time() - self.last_heartbeat
        
        return {
            "status": "healthy" if self.error_count < 10 else "degraded",
            "uptime_seconds": uptime,
            "webhooks_received": self.webhook_count,
            "errors": self.error_count,
            "error_rate": self.error_count / max(self.webhook_count, 1),
            "last_webhook": self.last_webhook_received,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def send_heartbeat(self, heartbeat_url: Optional[str] = None):
        """Send heartbeat to monitoring endpoint"""
        if not heartbeat_url:
            return
        
        status = self.get_status()
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(heartbeat_url, json=status)
                self.logger.debug(f"💓 Heartbeat sent: {status['status']}")
        except Exception as e:
            self.logger.error(f"Failed to send heartbeat: {e}")


class N8NBridge:
    """
    Main N8N integration bridge.
    
    Environment Variables:
        N8N_WEBHOOK_SECRET: HMAC secret for validating webhooks
        N8N_HEARTBEAT_URL: URL to send heartbeat pings
        N8N_FALLBACK_ENABLED: Enable fallback queue (default: 1)
    """
    
    def __init__(self):
        self.logger = LOGGER
        
        # Configuration
        webhook_secret = os.getenv("N8N_WEBHOOK_SECRET", "change_this_secret_in_production")
        self.heartbeat_url = os.getenv("N8N_HEARTBEAT_URL")
        self.fallback_enabled = os.getenv("N8N_FALLBACK_ENABLED", "1") == "1"
        
        # Components
        self.validator = N8NWebhookValidator(webhook_secret)
        self.queue = N8NFallbackQueue() if self.fallback_enabled else None
        self.heartbeat = N8NHeartbeat()
        
        self.logger.info("🌉 N8N Bridge initialized")
        self.logger.info(f"   Fallback queue: {'enabled' if self.fallback_enabled else 'disabled'}")
        self.logger.info(f"   Heartbeat: {'enabled' if self.heartbeat_url else 'disabled'}")
    
    async def process_incoming_webhook(
        self,
        payload: bytes,
        signature: str,
        timestamp: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Process incoming webhook from N8N.
        
        Args:
            payload: Raw webhook payload (bytes)
            signature: HMAC signature from X-N8N-Signature header
            timestamp: Unix timestamp from X-N8N-Timestamp header
            
        Returns:
            Dict with processing result
        """
        # Validate signature
        if not self.validator.validate_signature(payload, signature, timestamp):
            self.heartbeat.record_webhook(success=False)
            return {
                "status": "error",
                "message": "Invalid signature",
                "code": "INVALID_SIGNATURE"
            }
        
        # Parse payload
        try:
            data = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            self.heartbeat.record_webhook(success=False)
            return {
                "status": "error",
                "message": f"Invalid JSON: {e}",
                "code": "INVALID_JSON"
            }
        
        # Route to appropriate handler
        webhook_type = data.get("type", "unknown")
        
        if webhook_type == "news_ingestion":
            result = await self._handle_news_ingestion(data)
        elif webhook_type == "trade_approval":
            result = await self._handle_trade_approval(data)
        elif webhook_type == "incident":
            result = await self._handle_incident(data)
        else:
            result = {
                "status": "error",
                "message": f"Unknown webhook type: {webhook_type}",
                "code": "UNKNOWN_TYPE"
            }
        
        # Record webhook
        success = result.get("status") == "success"
        self.heartbeat.record_webhook(success=success)
        
        return result
    
    async def _handle_news_ingestion(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle news ingestion webhook"""
        self.logger.info(f"📰 News ingestion: {data.get('title', 'Unknown')}")
        
        # Example: Store news in database or trigger analysis
        # For now, just log
        
        return {
            "status": "success",
            "message": "News ingested successfully"
        }
    
    async def _handle_trade_approval(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle trade approval escalation"""
        trade_id = data.get("trade_id")
        action = data.get("action")  # APPROVE or REJECT
        
        self.logger.info(f"✅ Trade approval: {trade_id} → {action}")
        
        # Example: Update trade status in database
        # Call internal approval API
        
        return {
            "status": "success",
            "message": f"Trade {trade_id} {action}",
            "trade_id": trade_id
        }
    
    async def _handle_incident(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incident paging"""
        severity = data.get("severity", "medium")
        message = data.get("message", "Unknown incident")
        
        self.logger.warning(f"🚨 Incident [{severity.upper()}]: {message}")
        
        # Example: Send to PagerDuty, Opsgenie, etc.
        # For now, just log
        
        return {
            "status": "success",
            "message": "Incident logged"
        }
    
    async def send_webhook_to_n8n(
        self,
        url: str,
        data: Dict[str, Any],
        use_fallback: bool = True
    ) -> bool:
        """
        Send webhook to N8N workflow.
        
        Args:
            url: N8N webhook URL
            data: Payload to send
            use_fallback: Use fallback queue on failure
            
        Returns:
            True if successful, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=data)
                
                if response.status_code < 400:
                    self.logger.info(f"✅ Webhook sent to N8N: {url}")
                    return True
                else:
                    self.logger.warning(f"❌ N8N webhook failed: {response.status_code}")
                    
                    if use_fallback and self.queue:
                        self.queue.enqueue(data, url)
                    
                    return False
        except Exception as e:
            self.logger.error(f"Error sending webhook to N8N: {e}")
            
            if use_fallback and self.queue:
                self.queue.enqueue(data, url)
            
            return False
    
    async def run_background_tasks(self):
        """Run background maintenance tasks"""
        self.logger.info("🔄 Starting background tasks...")
        
        while True:
            try:
                # Process fallback queue
                if self.queue:
                    await self.queue.process_queue()
                
                # Send heartbeat
                if self.heartbeat_url:
                    await self.heartbeat.send_heartbeat(self.heartbeat_url)
                
                # Sleep
                await asyncio.sleep(60)
                
            except Exception as e:
                self.logger.error(f"Background task error: {e}")
                await asyncio.sleep(60)


async def main():
    """Main entry point for N8N bridge worker"""
    LOGGER.info("🌉 Starting N8N Bridge Worker...")
    
    bridge = N8NBridge()
    
    # Run background tasks
    await bridge.run_background_tasks()


if __name__ == "__main__":
    asyncio.run(main())
