#!/usr/bin/env python3
"""
Anthropic (Claude) Client
Provides async interface to Claude Sonnet 3.5 for trade analysis
"""
import os
import logging
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger("algogpt.anthropic_client")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-3-5-20241022").strip()
ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"

ENABLE_ANTHROPIC = os.getenv("ENABLE_ANTHROPIC", "1").lower() in ("1", "true", "yes") and bool(ANTHROPIC_API_KEY)


async def call_anthropic(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 500
) -> Optional[str]:
    """
    Call Anthropic (Claude) API with the given prompt
    
    Args:
        prompt: User prompt
        system: System instruction (optional)
        temperature: Sampling temperature (0.0-1.0)
        max_tokens: Maximum tokens to generate
        
    Returns:
        Generated text or None on failure
    """
    if not ENABLE_ANTHROPIC:
        logger.debug("Anthropic disabled or API key missing")
        return None
    
    try:
        url = f"{ANTHROPIC_BASE_URL}/messages"
        
        payload = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        if system:
            payload["system"] = system
        
        headers = {
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if "content" not in data or not data["content"]:
                logger.warning(f"No content in Anthropic response: {data}")
                return None
            
            text = data["content"][0]["text"]
            logger.debug(f"Anthropic response (first 100 chars): {text[:100]}")
            return text
            
    except httpx.HTTPStatusError as e:
        logger.error(f"Anthropic API HTTP error: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Anthropic API error: {e}", exc_info=True)
        return None


async def test_anthropic_connection() -> Dict[str, Any]:
    """
    Test Anthropic API connection
    
    Returns:
        Dict with ok, response, error
    """
    if not ENABLE_ANTHROPIC:
        return {"ok": False, "error": "Anthropic disabled or API key missing"}
    
    try:
        response = await call_anthropic(
            "Say 'OK' if you can hear me",
            system="You are a helpful assistant. Reply with exactly: OK",
            temperature=0.1,
            max_tokens=5
        )
        
        if response:
            return {"ok": True, "response": response.strip(), "model": ANTHROPIC_MODEL}
        else:
            return {"ok": False, "error": "No response from Anthropic"}
            
    except Exception as e:
        return {"ok": False, "error": str(e)}


__all__ = ["call_anthropic", "test_anthropic_connection", "ENABLE_ANTHROPIC", "ANTHROPIC_MODEL"]
