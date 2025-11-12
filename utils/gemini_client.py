#!/usr/bin/env python3
# utils/gemini_client.py
"""
Google Gemini AI Client
Provides async interface to Gemini 2 Pro for trade analysis
"""
import os
import logging
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger("algogpt.gemini_client")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp").strip()
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# 🚀 COST OPTIMIZATION: Gemini disabled by default (quota issues + cost)
# Set ENABLE_GEMINI=1 in environment to re-enable if needed
ENABLE_GEMINI = os.getenv("ENABLE_GEMINI", "0").lower() in ("1", "true", "yes") and bool(GEMINI_API_KEY)


async def call_gemini(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 500
) -> Optional[str]:
    """
    Call Gemini API with the given prompt
    
    Args:
        prompt: User prompt
        system: System instruction (optional)
        temperature: Sampling temperature (0.0-1.0)
        max_tokens: Maximum tokens to generate
        
    Returns:
        Generated text or None on failure
    """
    if not ENABLE_GEMINI:
        logger.debug("Gemini disabled or API key missing")
        return None
    
    try:
        url = f"{GEMINI_BASE_URL}/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        
        contents = []
        if system:
            contents.append({
                "role": "user",
                "parts": [{"text": f"System: {system}\n\nUser: {prompt}"}]
            })
        else:
            contents.append({
                "role": "user",
                "parts": [{"text": prompt}]
            })
        
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "topP": 0.95,
                "topK": 40
            }
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            
            if "candidates" not in data or not data["candidates"]:
                logger.warning(f"No candidates in Gemini response: {data}")
                return None
            
            candidate = data["candidates"][0]
            if "content" not in candidate or "parts" not in candidate["content"]:
                logger.warning(f"Invalid candidate structure: {candidate}")
                return None
            
            parts = candidate["content"]["parts"]
            if not parts or "text" not in parts[0]:
                logger.warning(f"No text in parts: {parts}")
                return None
            
            return parts[0]["text"].strip()
    
    except httpx.HTTPStatusError as e:
        logger.error(f"Gemini API HTTP error: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return None


async def gemini_healthcheck() -> Dict[str, Any]:
    """
    Health check for Gemini integration
    
    Returns:
        Health status dictionary
    """
    return {
        "ok": ENABLE_GEMINI,
        "api_key_set": bool(GEMINI_API_KEY),
        "model": GEMINI_MODEL,
        "enabled": ENABLE_GEMINI
    }


__all__ = ["call_gemini", "gemini_healthcheck", "ENABLE_GEMINI", "GEMINI_MODEL"]
