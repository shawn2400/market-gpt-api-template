# -*- coding: utf-8 -*-
from __future__ import annotations

import os, json, hmac, logging
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger("algogpt.llm")

LLM_PROVIDER      = os.getenv("LLM_PROVIDER", "deepseek").lower()
OPENAI_API_BASE   = os.getenv("OPENAI_API_BASE", os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"))
DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")

DEFAULT_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat") if LLM_PROVIDER == "deepseek" else os.getenv("OPENAI_MODEL", "gpt-5-2025-08-07")

def _ct_equal(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a or "", b or "")
    except Exception:
        return (a or "") == (b or "")

def _auth_header() -> str:
    key = DEEPSEEK_API_KEY if LLM_PROVIDER == "deepseek" else OPENAI_API_KEY
    if not key:
        raise RuntimeError(f"{'DEEPSEEK' if LLM_PROVIDER=='deepseek' else 'OPENAI'}_API_KEY missing")
    return f"Bearer {key}"

async def llm_chat_completion(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
    stream: bool = False,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """
    OpenAI-compatible /chat/completions
    Returns dict with keys: id, object, created, model, choices, usage...
    """
    url = OPENAI_API_BASE.rstrip("/") + "/chat/completions"
    payload: Dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "temperature": float(temperature),
        "stream": bool(stream),
    }
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    headers = {
        "Authorization": _auth_header(),
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=timeout) as cli:
        r = await cli.post(url, headers=headers, content=json.dumps(payload))
        if r.status_code >= 400:
            raise RuntimeError(f"LLM HTTP {r.status_code}: {r.text}")
        return r.json()

async def analyze_trading_signal(symbol: str, prompt: str) -> Dict[str, Any]:
    """
    החזרת ניתוח תכל׳ס מה-LLM עבור symbol.
    """
    messages = [
        {"role": "system", "content": "You are an expert cryptocurrency trading analyst. Provide concise, actionable analysis with SL/TP suggestions."},
        {"role": "user", "content": prompt}
    ]
    try:
        resp = await llm_chat_completion(messages, temperature=0.3)
        text = resp["choices"][0]["message"]["content"]
        return {"ok": True, "analysis": text, "model": resp.get("model", "unknown"), "usage": resp.get("usage", {})}
    except Exception as e:
        logger.exception("LLM analysis failed for %s", symbol)
        return {"ok": False, "error": str(e), "analysis": "Analysis unavailable"}

async def test_llm_connection() -> Dict[str, Any]:
    """
    בדיקת קישוריות ל-LLM.
    """
    test_messages = [
        {"role": "system", "content": "You are a helpful assistant. Reply with exactly: OK"},
        {"role": "user", "content": "Test connection - please respond with OK"}
    ]
    try:
        resp = await llm_chat_completion(test_messages, temperature=0.1, max_tokens=5)
        text = resp["choices"][0]["message"]["content"].strip()
        provider = "DeepSeek" if DEEPSEEK_API_KEY else "OpenAI"
        return {"ok": True, "provider": provider, "response": text, "model": resp.get("model", "unknown")}
    except Exception as e:
        return {"ok": False, "error": str(e), "provider": "DeepSeek" if DEEPSEEK_API_KEY else "OpenAI"}

__all__ = ["llm_chat_completion", "analyze_trading_signal", "test_llm_connection"]
