# utils/ai_client.py
from __future__ import annotations
import os, logging, asyncio
from typing import Optional
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

api_key = os.getenv("OPENAI_API_KEY", "").strip()
if not api_key:
    logger.error("❌ OPENAI_API_KEY not set!")

# יצירת לקוח OpenAI
client = AsyncOpenAI(api_key=api_key)

async def chat(prompt: str, system: str = "", temperature: float = 0.3, max_tokens: int = 256) -> Optional[str]:
    """
    Wrapper אסינכרוני ל־OpenAI ChatCompletion (API >= 1.0.0).
    """
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system or "You are a professional crypto analyst."},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error("❌ OpenAI chat failed: %s", e)
        return None













