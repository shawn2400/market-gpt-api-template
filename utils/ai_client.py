# utils/ai_client.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, logging
from typing import Optional, Dict

logger = logging.getLogger("algogpt.ai")

# optional openai client
try:
    from openai import AsyncOpenAI  # type: ignore
except Exception:
    AsyncOpenAI = None  # type: ignore

_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

_client = None
if AsyncOpenAI and _API_KEY:
    try:
        _client = AsyncOpenAI(api_key=_API_KEY)
    except Exception as e:
        logger.warning("OpenAI init failed: %s", e)
        _client = None

async def chat(
    prompt: str,
    system: str = "You are a professional crypto analyst.",
    temperature: float = 0.3,
    max_tokens: int = 256,
    model: Optional[str] = None,
) -> Optional[str]:
    if not _client:
        return None
    try:
        resp = await _client.chat.completions.create(
            model=model or _MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("OpenAI chat failed: %s", e)
        return None

def ai_healthcheck() -> Dict[str, object]:
    """שמור מינימלי לבריאות – לא קורא לרשת, רק מצהיר על זמינות."""
    return {
        "ok": True,
        "client": bool(_client),
        "model": _MODEL,
        "api_key_set": bool(_API_KEY),
    }

__all__ = ["chat", "ai_healthcheck"]














