# utils/ai_client.py
from __future__ import annotations
import os, logging, openai, asyncio
from typing import Optional

logger = logging.getLogger(__name__)

openai.api_key = os.getenv("OPENAI_API_KEY", "").strip()

if not openai.api_key:
    logger.error("❌ OPENAI_API_KEY not set!")

async def chat(prompt: str, system: str = "", temperature: float = 0.3, max_tokens: int = 256) -> Optional[str]:
    """
    Wrapper אסינכרוני ל־OpenAI ChatCompletion.
    """
    try:
        resp = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system or "You are a professional crypto analyst."},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error("❌ OpenAI chat failed: %s", e)
        return None












