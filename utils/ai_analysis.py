# utils/ai_analysis.py
from __future__ import annotations
import os, asyncio, random
from typing import Dict, Any, List, Optional

import httpx

# ========= ENV / Tuning =========
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-2025-08-07")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
OPENAI_MAX_CONCURRENCY = int(os.getenv("OPENAI_MAX_CONCURRENCY", "4"))

# thresholds (ברירת מחדל: 8.5 ו-0.2)
AI_MIN_QUALITY = float(os.getenv("AI_MIN_QUALITY", "8.5"))
AI_CONFLICT_MIN = float(os.getenv("AI_CONFLICT_MIN", "0.2"))

# Retry / Backoff
AI_HTTP_RETRIES = int(os.getenv("AI_HTTP_RETRIES", "3"))
AI_HTTP_BACKOFF_BASE = float(os.getenv("AI_HTTP_BACKOFF_BASE", "0.6"))
AI_HTTP_BACKOFF_MAX = float(os.getenv("AI_HTTP_BACKOFF_MAX", "4.0"))

# Concurrency semaphore (process-wide)
_sema = asyncio.Semaphore(max(1, OPENAI_MAX_CONCURRENCY))


def _to_float_safe(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _build(features: Dict[str, Any]) -> Dict[str, Any]:
    """בונה payload ‘עמיד’ עבור chat.completions – קצר וקונסיסטנטי."""
    sym = str(features.get("symbol") or "?").upper()
    parts = []
    for k, v in features.items():
        if v is None:
            continue
        try:
            s = str(v)
            if len(s) > 80:
                s = s[:77] + "..."
            parts.append(f"{k}={s}")
        except Exception:
            parts.append(f"{k}=[unserializable]")
    summary = ", ".join(parts[:60])  # תקרת אורך סבירה

    return {
        "model": OPENAI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a concise crypto futures analyst. "
                    "Return a short, structured opinion with key levels if applicable. "
                    "Avoid fluff. Hebrew or English is OK."
                ),
            },
            {"role": "user", "content": f"Symbol={sym}\nFeatures={summary}"},
        ],
        "temperature": 0.2,
        "max_tokens": 350,
    }


def _need_ai(features: Dict[str, Any]) -> bool:
    """
    החלטה מוקדמת אם שווה להריץ AI:
      - quality_score (0..10) אם קיים
      - אחרת final_prob (0..1) * 10
      - וגם רמת conflict (0..1)
    """
    q_raw = features.get("quality_score")
    if q_raw is None:
        q_raw = (_to_float_safe(features.get("final_prob"), 0.0) * 10.0)
    q = _to_float_safe(q_raw, 0.0)
    conflict = _to_float_safe(features.get("vote_conflict"), 0.0)
    return (q >= AI_MIN_QUALITY) or (conflict >= AI_CONFLICT_MIN)


def _jitter(v: float, pct: float = 0.12) -> float:
    d = v * pct
    return max(0.0, v + random.uniform(-d, d))


async def _post_json_with_retry(url: str, *, headers: Dict[str, str], json_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    POST עם backoff+retry רך על 429/5xx ושגיאות רשת.
    """
    attempt = 0
    backoff = AI_HTTP_BACKOFF_BASE
    last_err: Optional[Exception] = None
    max_attempts = max(1, AI_HTTP_RETRIES)

    while attempt < max_attempts:
        attempt += 1
        try:
            async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT) as client:
                r = await client.post(url, headers=headers, json=json_payload)
                if r.status_code in (429, 500, 502, 503, 504):
                    # retryable
                    last_err = httpx.HTTPStatusError("AI upstream retryable", request=r.request, response=r)
                    await asyncio.sleep(_jitter(min(backoff, AI_HTTP_BACKOFF_MAX)))
                    backoff = min(AI_HTTP_BACKOFF_MAX, backoff * 1.7)
                    continue
                r.raise_for_status()
                return r.json()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as e:
            last_err = e
            await asyncio.sleep(_jitter(min(backoff, AI_HTTP_BACKOFF_MAX)))
            backoff = min(AI_HTTP_BACKOFF_MAX, backoff * 1.7)
        except Exception as e:
            # שגיאה לא צפויה – לא ננסה שוב כדי לא “להילחם” בבעיית תוכן
            raise e

    if last_err:
        raise last_err
    raise RuntimeError("AI request failed with unknown error")


async def analyze_with_ai(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    מחזיר: {"ok": bool, "analysis": str}
    - אם אין מפתח API: חוזר עם ok=False וניתוח מינימלי.
    - אם quality נמוך מאוד ואין קונפליקט קולות: מדלגים (חיסכון בעלויות/לטנסי).
    - כולל retries רכים על 429/5xx.
    """
    if not OPENAI_API_KEY:
        return {"ok": False, "analysis": "[AI disabled]"}

    if not _need_ai(features):
        return {"ok": False, "analysis": "[AI skipped] below thresholds"}

    payload = _build(features)
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    async with _sema:
        try:
            data = await _post_json_with_retry(f"{OPENAI_BASE_URL}/chat/completions", headers=headers, json_payload=payload)
            # מבנה chat.completions קלאסי
            msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
            txt = (msg.get("content") or "").strip()
            return {"ok": True, "analysis": txt or "[AI empty]"}
        except Exception as e:
            # כשל רך שלא שובר זרימה
            return {"ok": False, "analysis": f"[AI error: {e}]"}


# -------- analyze_with_ai_and_filter --------
async def analyze_with_ai_and_filter(
    *,
    symbols: List[str],
    interval: str,
    market: str,
    max_items: int = 10,
    run_early_approvals: bool = True,
) -> Dict[str, Any]:
    """
    מחזיר:
      {
        "accepted": [ {symbol, side, entry, sl, tp1, leverage, success_pct, reason} ... ],
        "rejected": [ {symbol, reason} ... ]
      }
    """
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    limit = max(0, int(max_items))
    for s in symbols[:limit]:
        su = str(s or "").upper().strip()
        if not su:
            rejected.append({"symbol": str(s), "reason": "empty_symbol"})
            continue
        try:
            accepted.append(
                {
                    "symbol": su,
                    "side": "LONG",
                    "entry": None,  # יושלם downstream לפי מחיר חי
                    "sl": None,
                    "tp1": None,
                    "leverage": 10,
                    "success_pct": 0.55,
                    "reason": f"preliminary filter ({interval}/{market})",
                }
            )
        except Exception as e:
            rejected.append({"symbol": su, "reason": f"filter_error: {e}"})

    return {"accepted": accepted, "rejected": rejected}
















































