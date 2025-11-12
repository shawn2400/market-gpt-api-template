#!/usr/bin/env python3
"""
Qwen 2.5 Turbo Client (FREE!)
Provides async interface to Alibaba Cloud Qwen 2.5 for trade analysis
"""
import os
import logging
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger("algogpt.qwen_client")

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip()
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-turbo").strip()
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"

# ⚠️ SUSPENDED: Invalid Qwen API key (needs DashScope API key, not Access Key)
# Can be re-enabled by setting ENABLE_QWEN=1 env var with valid DashScope key
ENABLE_QWEN = os.getenv("ENABLE_QWEN", "0").lower() in ("1", "true", "yes") and bool(DASHSCOPE_API_KEY)


async def call_qwen(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 300
) -> Optional[str]:
    """
    Call Qwen 2.5 Turbo API with the given prompt
    
    Args:
        prompt: User prompt
        system: System instruction (optional)
        temperature: Sampling temperature (0.0-1.0)
        max_tokens: Maximum tokens to generate (default 300 for cost optimization)
        
    Returns:
        Generated text or None on failure
    """
    if not ENABLE_QWEN:
        logger.debug("Qwen disabled or API key missing")
        return None
    
    try:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": QWEN_MODEL,
            "input": {
                "messages": messages
            },
            "parameters": {
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": 0.8,
                "result_format": "message"
            }
        }
        
        headers = {
            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(QWEN_BASE_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if "output" not in data:
                logger.warning(f"No output in Qwen response: {data}")
                return None
            
            output = data["output"]
            if "choices" not in output or not output["choices"]:
                logger.warning(f"No choices in Qwen output: {output}")
                return None
            
            choice = output["choices"][0]
            if "message" not in choice or "content" not in choice["message"]:
                logger.warning(f"Invalid choice structure: {choice}")
                return None
            
            text = choice["message"]["content"]
            logger.debug(f"Qwen response (first 100 chars): {text[:100]}")
            return text
            
    except httpx.HTTPStatusError as e:
        error_text = e.response.text
        logger.error(f"Qwen API HTTP error: {e.response.status_code} - {error_text}")
        
        if e.response.status_code == 429:
            logger.warning("Qwen rate limit exceeded - will auto-suspend")
        elif e.response.status_code == 401:
            logger.error("Qwen API key invalid or expired")
        
        return None
    except httpx.TimeoutException:
        logger.error("Qwen API timeout - slow response")
        return None
    except Exception as e:
        logger.error(f"Qwen API error: {e}", exc_info=True)
        return None


async def test_qwen_connection() -> Dict[str, Any]:
    """
    Test Qwen API connection
    
    Returns:
        Dict with ok, response, error
    """
    if not ENABLE_QWEN:
        return {"ok": False, "error": "Qwen disabled or API key missing"}
    
    try:
        response = await call_qwen(
            "Say 'OK' if you can hear me",
            system="You are a helpful assistant. Reply with exactly: OK",
            temperature=0.1,
            max_tokens=5
        )
        
        if response:
            return {"ok": True, "response": response.strip(), "model": QWEN_MODEL}
        else:
            return {"ok": False, "error": "No response from Qwen"}
            
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def qwen_healthcheck() -> Dict[str, Any]:
    """
    Health check for Qwen integration
    
    Returns:
        Health status dictionary
    """
    if not ENABLE_QWEN:
        return {
            "provider": "Qwen 2.5 Turbo",
            "status": "disabled",
            "reason": "ENABLE_QWEN=0 or missing API key",
            "cost_per_call": "$0.00 (FREE!)"
        }
    
    connection_test = await test_qwen_connection()
    
    return {
        "provider": "Qwen 2.5 Turbo",
        "model": QWEN_MODEL,
        "status": "healthy" if connection_test["ok"] else "error",
        "enabled": ENABLE_QWEN,
        "api_key_present": bool(DASHSCOPE_API_KEY),
        "connection_test": connection_test,
        "cost_per_call": "$0.00 (FREE!)",
        "features": ["Ultra-fast", "Free tier", "Chinese + English"]
    }


if __name__ == "__main__":
    import asyncio
    
    async def main():
        print("🧪 Testing Qwen 2.5 Turbo connection...\n")
        
        health = await qwen_healthcheck()
        print(f"Provider: {health['provider']}")
        print(f"Status: {health['status']}")
        print(f"Enabled: {health.get('enabled', False)}")
        print(f"Cost: {health['cost_per_call']}")
        
        if health['status'] == 'healthy':
            print("\n✅ Qwen 2.5 Turbo is ready!")
        else:
            print(f"\n❌ Error: {health.get('connection_test', {}).get('error', 'Unknown')}")
    
    asyncio.run(main())
