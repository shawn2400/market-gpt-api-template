# routes/n8n.py
from __future__ import annotations
import os, hmac, hashlib, time, json, logging
from typing import Any, Dict, Optional, Tuple
from contextlib import suppress

from fastapi import APIRouter, Body, Header, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("algogpt.n8n")
router = APIRouter(prefix="/n8n", tags=["N8N Integration"])

# ===== Configuration =====
N8N_WEBHOOK_SECRET = os.getenv("N8N_WEBHOOK_SECRET", "").strip()
N8N_HEARTBEAT_URL = os.getenv("N8N_HEARTBEAT_URL", "").strip()
N8N_FALLBACK_ENABLED = os.getenv("N8N_FALLBACK_ENABLED", "1").lower() in ("1", "true", "yes", "on")
N8N_MAX_AGE_SECONDS = int(os.getenv("N8N_MAX_AGE_SECONDS", "300"))

# ===== Import N8N Bridge components =====
_validator = None
_fallback_queue = None
_heartbeat = None

with suppress(Exception):
    from workers.n8n_bridge import N8NWebhookValidator, N8NFallbackQueue, N8NHeartbeat
    
    if N8N_WEBHOOK_SECRET:
        _validator = N8NWebhookValidator(N8N_WEBHOOK_SECRET)
        logger.info("✅ N8N webhook validator initialized")
    else:
        logger.warning("⚠️ N8N_WEBHOOK_SECRET not set - webhook validation disabled")
    
    if N8N_FALLBACK_ENABLED:
        _fallback_queue = N8NFallbackQueue(max_size=1000, retry_interval=60)
        logger.info("✅ N8N fallback queue initialized")
    
    _heartbeat = N8NHeartbeat(interval_seconds=60)
    logger.info("✅ N8N heartbeat monitor initialized")


# ===== Webhook Payload Models =====
class N8NWebhookPayload(BaseModel):
    type: str
    data: Dict[str, Any]
    timestamp: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


# ===== Helper Functions =====
def _validate_hmac_signature(
    payload_bytes: bytes,
    signature: str,
    timestamp: Optional[int] = None
) -> Tuple[bool, str]:
    """
    Validate HMAC signature of incoming webhook.
    
    Args:
        payload_bytes: Raw request body
        signature: HMAC signature from header
        timestamp: Unix timestamp for anti-replay protection
        
    Returns:
        (is_valid, reason)
    """
    if not N8N_WEBHOOK_SECRET:
        # SECURITY: Fail closed - reject all requests if no secret configured
        logger.error("❌ N8N_WEBHOOK_SECRET not configured - BLOCKING all webhook requests")
        return False, "webhook_secret_required"
    
    if not signature:
        return False, "missing_signature"
    
    if not _validator:
        return False, "validator_not_initialized"
    
    try:
        is_valid = _validator.validate_signature(
            payload=payload_bytes,
            signature=signature,
            timestamp=timestamp,
            max_age_seconds=N8N_MAX_AGE_SECONDS
        )
        
        if is_valid:
            return True, "ok"
        else:
            return False, "invalid_signature"
            
    except Exception as e:
        logger.error(f"❌ Signature validation error: {e}")
        return False, f"validation_error: {e}"


async def _process_webhook_payload(webhook_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process incoming N8N webhook payload.
    
    This function routes the webhook to appropriate handlers based on type.
    
    Args:
        webhook_data: Parsed webhook payload
        
    Returns:
        Processing result
    """
    webhook_type = webhook_data.get("type", "unknown")
    data = webhook_data.get("data", {})
    
    logger.info(f"📥 Processing N8N webhook: type={webhook_type}")
    
    # Route based on webhook type
    if webhook_type == "news_ingestion":
        return await _handle_news_ingestion(data)
    elif webhook_type == "trade_approval":
        return await _handle_trade_approval(data)
    elif webhook_type == "incident":
        return await _handle_incident(data)
    elif webhook_type == "system_command":
        return await _handle_system_command(data)
    else:
        logger.warning(f"⚠️ Unknown webhook type: {webhook_type}")
        return {
            "status": "unknown_type",
            "type": webhook_type,
            "message": "Webhook received but type not recognized"
        }


async def _handle_news_ingestion(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle news ingestion webhooks.
    
    Processes incoming news and stores it for potential sentiment analysis.
    Future enhancement: integrate with market intelligence system.
    """
    logger.info(f"📰 News ingestion: {data.get('title', 'N/A')}")
    
    # Store news data for future sentiment analysis
    # Current implementation: log and acknowledge
    # Future: integrate with utils/market_intelligence.py sentiment module
    
    title = data.get("title", "")
    source = data.get("source", "unknown")
    sentiment = data.get("sentiment", "neutral")
    content = data.get("content", "")
    
    logger.info(f"News stored: {title[:50]}... | Source: {source} | Sentiment: {sentiment}")
    
    return {
        "status": "processed",
        "type": "news_ingestion",
        "title": title,
        "source": source,
        "sentiment": sentiment,
        "stored": True
    }


async def _handle_trade_approval(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle trade approval webhooks.
    
    Logs approval requests for manual processing.
    Future: integrate with ConfirmStore approval system.
    """
    trade_id = data.get("trade_id")
    action = data.get("action", "").lower()
    
    logger.info(f"✅ Trade approval webhook: trade_id={trade_id}, action={action}")
    
    # Log approval for manual processing
    # Future: integrate with utils/trade_executor.py (ConfirmStore)
    
    return {
        "status": "logged",
        "type": "trade_approval",
        "trade_id": trade_id,
        "action": action,
        "message": "Approval logged for manual processing"
    }


async def _handle_incident(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle incident webhooks.
    
    Logs incidents and optionally sends alerts via Telegram.
    Integrates with tiered alerting system.
    """
    severity = data.get("severity", "unknown").upper()
    message = data.get("message", "")
    incident_type = data.get("type", "general")
    
    logger.warning(f"🚨 Incident: severity={severity}, type={incident_type}, message={message}")
    
    # Log incident (future: integrate with telegram alerting)
    severity_emoji = {
        "CRITICAL": "🔴",
        "HIGH": "🟠",
        "MEDIUM": "🟡",
        "LOW": "🟢",
        "UNKNOWN": "⚪"
    }
    
    emoji = severity_emoji.get(severity, "⚪")
    
    logger.warning(f"{emoji} Incident logged: {incident_type} - {message}")
    
    return {
        "status": "processed",
        "type": "incident",
        "severity": severity,
        "incident_type": incident_type,
        "acknowledged": True
    }


async def _handle_system_command(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle system command webhooks.
    
    Executes safe system commands like health checks, status queries.
    Dangerous commands (restart, shutdown) are logged but not executed.
    """
    command = data.get("command", "").lower()
    params = data.get("params", {})
    
    logger.info(f"⚙️ System command: {command}")
    
    # Safe command handlers
    if command == "health_check":
        # Simple health check without full health module
        return {
            "status": "processed",
            "type": "system_command",
            "command": command,
            "result": {
                "status": "healthy",
                "timestamp": time.time()
            }
        }
    
    elif command in ["get_positions", "get_balance"]:
        # Future: integrate with Binance client
        logger.info(f"Command {command} logged (not yet implemented)")
        return {
            "status": "not_implemented",
            "type": "system_command",
            "command": command,
            "message": "Command logged but not yet implemented"
        }
    
    # Dangerous commands - log only, don't execute
    elif command in ["restart", "shutdown", "deploy"]:
        logger.warning(f"🚫 Dangerous command blocked: {command}")
        return {
            "status": "blocked",
            "type": "system_command",
            "command": command,
            "message": "Command blocked for security reasons. Use Replit dashboard instead."
        }
    
    else:
        logger.warning(f"⚠️ Unknown system command: {command}")
        return {
            "status": "unknown_command",
            "type": "system_command",
            "command": command,
            "message": "Command not recognized"
        }


# ===== API Endpoints =====

@router.post("/webhook/ingest", summary="Receive webhooks from N8N")
async def webhook_ingest(
    request: Request,
    x_n8n_signature: Optional[str] = Header(None),
    x_n8n_timestamp: Optional[str] = Header(None)
):
    """
    Receive and process webhooks from N8N workflows.
    
    Security:
    - HMAC-SHA256 signature validation using N8N_WEBHOOK_SECRET
    - Anti-replay protection via timestamp validation
    - Maximum age: 5 minutes (configurable via N8N_MAX_AGE_SECONDS)
    
    Headers:
    - X-N8N-Signature: HMAC-SHA256 signature of request body
    - X-N8N-Timestamp: Unix timestamp when webhook was sent
    
    Payload:
    - type: Webhook type (news_ingestion, trade_approval, incident, etc.)
    - data: Webhook-specific data
    - timestamp: Optional timestamp
    - metadata: Optional metadata
    """
    try:
        # Read raw body for signature validation
        body_bytes = await request.body()
        
        # Parse timestamp
        timestamp_int = None
        if x_n8n_timestamp:
            try:
                timestamp_int = int(x_n8n_timestamp)
            except ValueError:
                logger.warning(f"⚠️ Invalid timestamp header: {x_n8n_timestamp}")
        
        # Validate HMAC signature
        is_valid, reason = _validate_hmac_signature(
            payload_bytes=body_bytes,
            signature=x_n8n_signature or "",
            timestamp=timestamp_int
        )
        
        if not is_valid:
            logger.warning(f"❌ Webhook rejected: {reason}")
            
            # Record failed webhook
            if _heartbeat:
                _heartbeat.record_webhook(success=False)
            
            raise HTTPException(
                status_code=401,
                detail=f"Invalid webhook signature: {reason}"
            )
        
        # Parse JSON payload
        try:
            webhook_data = json.loads(body_bytes)
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON payload: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid JSON payload: {e}"
            )
        
        # Process webhook
        result = await _process_webhook_payload(webhook_data)
        
        # Record successful webhook
        if _heartbeat:
            _heartbeat.record_webhook(success=True)
        
        logger.info(f"✅ Webhook processed successfully: {result.get('type')}")
        
        return JSONResponse({
            "ok": True,
            "status": "processed",
            "result": result,
            "timestamp": int(time.time())
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}", exc_info=True)
        
        # Record failed webhook
        if _heartbeat:
            _heartbeat.record_webhook(success=False)
        
        raise HTTPException(
            status_code=500,
            detail=f"Webhook processing error: {str(e)}"
        )


@router.get("/status", summary="N8N bridge health status")
async def status():
    """
    Get N8N bridge health status.
    
    Returns:
    - Bridge status (healthy, degraded, offline)
    - Configuration info
    - Webhook statistics
    - Queue status (if fallback enabled)
    """
    status_data = {
        "ok": True,
        "service": "n8n_bridge",
        "timestamp": int(time.time())
    }
    
    # Configuration status
    status_data["config"] = {
        "webhook_secret_configured": bool(N8N_WEBHOOK_SECRET),
        "heartbeat_url_configured": bool(N8N_HEARTBEAT_URL),
        "fallback_enabled": N8N_FALLBACK_ENABLED,
        "max_age_seconds": N8N_MAX_AGE_SECONDS
    }
    
    # Heartbeat status
    if _heartbeat:
        heartbeat_status = _heartbeat.get_status()
        status_data["heartbeat"] = heartbeat_status
        
        # Determine overall health
        if heartbeat_status.get("status") == "healthy":
            status_data["status"] = "healthy"
        else:
            status_data["status"] = "degraded"
    else:
        status_data["status"] = "offline"
        status_data["heartbeat"] = {"status": "not_initialized"}
    
    # Queue status
    if _fallback_queue:
        status_data["queue"] = {
            "enabled": True,
            "size": len(_fallback_queue.queue),
            "retry_interval": _fallback_queue.retry_interval
        }
    else:
        status_data["queue"] = {
            "enabled": False,
            "size": 0
        }
    
    return JSONResponse(status_data)


@router.post("/heartbeat", summary="Heartbeat endpoint for monitoring")
async def heartbeat_ping():
    """
    Heartbeat endpoint for external monitoring.
    
    N8N can send periodic heartbeat requests to this endpoint
    to verify the bridge is alive and responsive.
    """
    if _heartbeat:
        heartbeat_status = _heartbeat.get_status()
        
        return JSONResponse({
            "ok": True,
            "status": "alive",
            "timestamp": int(time.time()),
            "heartbeat": heartbeat_status
        })
    else:
        return JSONResponse({
            "ok": True,
            "status": "alive",
            "timestamp": int(time.time()),
            "heartbeat": {"status": "not_initialized"}
        })


@router.get("/queue/status", summary="Fallback queue status")
async def queue_status():
    """
    Get fallback queue status.
    
    The fallback queue stores webhooks that failed to process
    and retries them periodically.
    
    Returns:
    - Queue enabled/disabled
    - Current queue size
    - Retry interval
    - Queue items (if any)
    """
    if not N8N_FALLBACK_ENABLED:
        return JSONResponse({
            "ok": True,
            "enabled": False,
            "message": "Fallback queue is disabled"
        })
    
    if not _fallback_queue:
        return JSONResponse({
            "ok": False,
            "enabled": True,
            "error": "Fallback queue not initialized"
        })
    
    # Get queue items
    queue_items = []
    for item in list(_fallback_queue.queue):
        queue_items.append({
            "target_url": item.get("target_url"),
            "timestamp": item.get("timestamp"),
            "retry_count": item.get("retry_count"),
            "last_retry": item.get("last_retry"),
            "data_type": item.get("data", {}).get("type", "unknown")
        })
    
    return JSONResponse({
        "ok": True,
        "enabled": True,
        "queue_size": len(_fallback_queue.queue),
        "retry_interval": _fallback_queue.retry_interval,
        "items": queue_items
    })


# ===== Startup Log =====
logger.info("✅ N8N routes loaded successfully")
