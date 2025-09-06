# utils/ai_analysis.py
from __future__ import annotations
import os, json, asyncio, httpx
from typing import Dict, Any, Optional

# ENV
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o").strip()
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30.0"))
OPENAI_MAX_CONCURRENCY = int(os.getenv("OPENAI_MAX_CONCURRENCY", "4"))

_sema = asyncio.Semaphore(max(1, OPENAI_MAX_CONCURRENCY))

def _build_prompt(features: Dict[str, Any]) -> Dict[str, Any]:
    symbol = features.get("symbol", "UNKNOWN")
    summary = ", ".join([f"{k}={v}" for k,v in features.items() if v is not None])
    system = "You are an expert technical analyst for crypto futures. Write a concise, structured analysis."
    user = f"Symbol: {symbol}\nFeatures: {summary}"
    return {"model": OPENAI_MODEL,
            "messages":[{"role":"system","content":system},{"role":"user","content":user}],
            "temperature":0.2,"max_tokens":350}

async def _post(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT_SECONDS) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

async def analyze_with_ai(features: Dict[str, Any]) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        return {"ok": False, "analysis": "[AI disabled] Missing OPENAI_API_KEY."}
    payload = _build_prompt(features)
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    url = f"{OPENAI_BASE_URL}/chat/completions"
    async with _sema:
        try:
            data = await _post(url, headers, payload)
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
            if text:
                return {"ok": True, "analysis": text}
            return {"ok": False, "analysis": "[AI error] Empty response."}
        except Exception as e:
            return {"ok": False, "analysis": f"[AI exception: {e}]"}













































