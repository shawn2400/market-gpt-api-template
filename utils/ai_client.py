# utils/ai_client.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import logging
from typing import Optional, Dict

from utils.metrics_tracker import observe_http_ctx_async  # מטריקות HTTP

logger = logging.getLogger("algogpt.ai")

# Optional OpenAI client (graceful fallback if lib/env missing)
try:
    from openai import AsyncOpenAI  # type: ignore
except Exception:
    AsyncOpenAI = None  # type: ignore

_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-2025-08-07").strip()
_BASE_URL = (os.getenv("OPENAI_BASE") or os.getenv("OPENAI_BASE_URL") or "").strip()

_client = None
if AsyncOpenAI and _API_KEY:
    try:
        # allow overriding base_url via env if provided
        _client = AsyncOpenAI(api_key=_API_KEY, base_url=_BASE_URL or None)
    except Exception as e:
        logger.warning("OpenAI init failed: %s", e)
        _client = None
else:
    if not _API_KEY:
        logger.info("OPENAI_API_KEY not set; AI features disabled")
    if not AsyncOpenAI:
        logger.info("openai SDK not available; AI features disabled")

async def chat(
    prompt: str,
    system: str = "You are a professional crypto analyst.",
    temperature: float = 0.3,
    max_tokens: int = 256,
    model: Optional[str] = None,
) -> Optional[str]:
    """
    Async chat wrapper. Returns str on success or None on failure/unavailable.
    """
    if not _client:
        return None
    try:
        # עוטפים את הקריאה האסינכרונית במטריקת HTTP כללית
        async with observe_http_ctx_async(name="openai_chat"):
            resp = await _client.chat.completions.create(
                model=(model or _MODEL),
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
            )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("OpenAI chat failed: %s", e)
        return None

async def ai_healthcheck() -> Dict[str, object]:
    """
    Lightweight async health: no network call.
    שמרתי אסינכרוני כדי להתאים ל- await _ai_check() ב-/health/ai
    """
    return {
        "ok": True,                    # module loaded
        "client": bool(_client),       # client constructed
        "model": _MODEL,
        "api_key_set": bool(_API_KEY),
        "base_url": _BASE_URL or "https://api.openai.com/v1",
    }

def ai_healthcheck_sync() -> Dict[str, object]:
    """גרסה סינכרונית למי שצריך."""
    return {
        "ok": True,
        "client": bool(_client),
        "model": _MODEL,
        "api_key_set": bool(_API_KEY),
        "base_url": _BASE_URL or "https://api.openai.com/v1",
    }

__all__ = ["chat", "ai_healthcheck", "ai_healthcheck_sync"]








