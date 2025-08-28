# utils/ai_analysis.py
from __future__ import annotations

import os
import json
import math
import asyncio
from typing import Dict, Any, Optional

import httpx

# ENV
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o").strip()
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30.0"))
OPENAI_MAX_CONCURRENCY = int(os.getenv("OPENAI_MAX_CONCURRENCY", "4"))

# סמאפור להגבלת עומס פנימי
_sema = asyncio.Semaphore(max(1, OPENAI_MAX_CONCURRENCY))

# Backoff בסיסי
def _backoff(attempt: int) -> float:
    return min(0.6 * (2 ** attempt), 5.0)

def _build_prompt(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    בונה פרומפט מינימלי: המטרה – ניתוח טכני קצר, ממוקד, ללא המלצה מחייבת.
    """
    symbol = features.get("symbol", "UNKNOWN")
    # תעבור על שדות שכיחים אם קיימים
    keys = [
        "close", "open", "high", "low", "volume",
        "ema21", "ema50", "rsi", "macd", "macd_signal", "macd_hist",
        "adx", "atr",
    ]
    # בנה תקציר מאונדקס
    parts = []
    for k in keys:
        v = features.get(k)
        if v is None:
            continue
        try:
            if isinstance(v, (int, float)):
                parts.append(f"{k}={v:.6g}")
            else:
                parts.append(f"{k}={v}")
        except Exception:
            parts.append(f"{k}={v}")
    summary = ", ".join(parts)

    system = (
        "You are an expert technical analyst for crypto futures. "
        "Return a concise, actionable analysis (3-6 bullets) of the latest candle/indicators. "
        "Do NOT give financial advice; use neutral language. "
        "Focus on momentum, trend alignment (EMA21/EMA50), RSI regimes, ADX strength, "
        "volatility via ATR, and potential invalidation levels."
    )
    user = f"Symbol: {symbol}\nFeatures: {summary}\nTask: Provide concise technical analysis."

    # chat.completions payload
    return {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 350,
    }

async def _post_with_retries(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
    last_err: Optional[str] = None
    for attempt in range(5):
        try:
            timeout = httpx.Timeout(OPENAI_TIMEOUT_SECONDS)
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, headers=headers, json=payload)
                # 429/5xx → ננסה שוב עם backoff
                if r.status_code in (429, 500, 502, 503, 504):
                    last_err = f"{r.status_code}: {r.text[:300]}"
                    await asyncio.sleep(_backoff(attempt))
                    continue
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as e:
            try:
                data = e.response.json()
                last_err = json.dumps(data)[:300]
            except Exception:
                last_err = e.response.text[:300]
            # 4xx אחרים – אין טעם להמשיך
            if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                break
        except Exception as e:
            last_err = str(e)
            await asyncio.sleep(_backoff(attempt))
    raise RuntimeError(f"OpenAI request failed after retries: {last_err}")

async def analyze_with_ai(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    קלט: מילון של פיצ'רים (שורה אחרונה של אינדיקטורים + symbol)
    פלט: {"ok": bool, "analysis": str}
    """
    if not OPENAI_API_KEY:
        return {"ok": False, "analysis": "[AI disabled] Missing OPENAI_API_KEY."}

    payload = _build_prompt(features)
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{OPENAI_BASE_URL}/chat/completions"

    async with _sema:
        data = await _post_with_retries(url, headers, payload)

    # חילוץ הטקסט בבטחה
    text = ""
    try:
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
    except Exception:
        text = ""

    if not text:
        return {"ok": False, "analysis": "[AI error] Empty response."}
    return {"ok": True, "analysis": text}












































