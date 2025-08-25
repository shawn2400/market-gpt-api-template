# utils/ai_client.py
from __future__ import annotations
import os, logging
from typing import Optional
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# --- Load API key ---
api_key = os.getenv("OPENAI_API_KEY", "").strip()
if not api_key:
    logger.error("❌ OPENAI_API_KEY not set!")

# --- Create OpenAI client ---
client: Optional[AsyncOpenAI] = None
if api_key:
    try:
        client = AsyncOpenAI(api_key=api_key)
    except Exception as e:
        logger.error("❌ Failed to init AsyncOpenAI: %s", e)
        client = None


async def chat(
    prompt: str,
    system: str = "You are a professional crypto analyst.",
    temperature: float = 0.3,
    max_tokens: int = 256,
    model: str | None = None,
) -> Optional[str]:
    """
    Async wrapper ל־OpenAI ChatCompletion (API >= 1.0.0).
    מחזיר string או None אם נכשל.
    """
    if client is None:
        logger.error("❌ OpenAI client not available")
        return None

    try:
        resp = await client.chat.completions.create(
            model=model or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error("❌ OpenAI chat failed: %s", e)
        return None















