#!/usr/bin/env python3
"""
XAI (Grok) Client
Provides async interface to Grok-2 for trade analysis
"""
import os
import logging
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger("algogpt.xai_client")

XAI_API_KEY = os.getenv("XAI_API_KEY", "").strip()
XAI_MODEL = os.getenv("XAI_MODEL", "grok-2-latest").strip()
XAI_BASE_URL = "https://api.x.ai/v1"

ENABLE_XAI = os.getenv("ENABLE_XAI", "1").lower() in ("1", "true", "yes") and bool(XAI_API_KEY)


async def call_xai(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 500
) -> Optional[str]:
    """
    Call XAI (Grok) API with the given prompt
    
    Args:
        prompt: User prompt
        system: System instruction (optional)
        temperature: Sampling temperature (0.0-1.0)
        max_tokens: Maximum tokens to generate
        
    Returns:
        Generated text or None on failure
    """
    if not ENABLE_XAI:
        logger.debug("XAI disabled or API key missing")
        return None
    
    try:
        url = f"{XAI_BASE_URL}/chat/completions"
        
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": XAI_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        headers = {
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if "choices" not in data or not data["choices"]:
                logger.warning(f"No choices in XAI response: {data}")
                return None
            
            text = data["choices"][0]["message"]["content"]
            logger.debug(f"XAI response (first 100 chars): {text[:100]}")
            return text
            
    except httpx.HTTPStatusError as e:
        logger.error(f"XAI API HTTP error: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"XAI API error: {e}", exc_info=True)
        return None


async def test_xai_connection() -> Dict[str, Any]:
    """
    Test XAI API connection
    
    Returns:
        Dict with ok, response, error
    """
    if not ENABLE_XAI:
        return {"ok": False, "error": "XAI disabled or API key missing"}
    
    try:
        response = await call_xai(
            "Say 'OK' if you can hear me",
            system="You are a helpful assistant. Reply with exactly: OK",
            temperature=0.1,
            max_tokens=5
        )
        
        if response:
            return {"ok": True, "response": response.strip(), "model": XAI_MODEL}
        else:
            return {"ok": False, "error": "No response from XAI"}
            
    except Exception as e:
        return {"ok": False, "error": str(e)}


__all__ = ["call_xai", "test_xai_connection", "ENABLE_XAI", "XAI_MODEL"]
