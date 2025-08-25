# utils/ai_client.py
from __future__ import annotations
import os, logging
from typing import Optional
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None
_api_key: Optional[str] = None


def _get_client() -> AsyncOpenAI:
    """
    Lazy-load OpenAI client – טוען את ה־API key בזמן אמת בכל קריאה.
    """
    global _client, _api_key
    key = os.getenv("OPENAI_API_KEY", "").strip()

    if not key:
        logger.error("❌ OPENAI_API_KEY not set (env empty)")
        raise RuntimeError("OPENAI_API_KEY missing")

    if _client is None or key != _api_key:
        _api_key = key
        _client = AsyncOpenAI(api_key=key)
        logger.info("✅ OpenAI client initialized (len=%d)", len(key))

    return _client


async def chat(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    max_tokens: int = 256,
) -> Optional[str]:
    """
    Wrapper אסינכרוני לקריאות GPT עם טעינה דינמית של API key.
    """
    try:
        client = _get_client()
        resp = await client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
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














