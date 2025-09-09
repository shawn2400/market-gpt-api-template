# utils/ai_analysis.py
from __future__ import annotations
import os, asyncio
from typing import Dict, Any, List, Optional

import httpx

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
OPENAI_MAX_CONCURRENCY = int(os.getenv("OPENAI_MAX_CONCURRENCY", "4"))

# thresholds (השארתי 8.5 כפי שביקשת)
AI_MIN_QUALITY = float(os.getenv("AI_MIN_QUALITY", "8.5"))
AI_CONFLICT_MIN = float(os.getenv("AI_CONFLICT_MIN", "0.2"))

_sema = asyncio.Semaphore(max(1, OPENAI_MAX_CONCURRENCY))


def _to_float_safe(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _build(features: Dict[str, Any]) -> Dict[str, Any]:
    sym = str(features.get("symbol") or "?").upper()
    # סיכום קצר ועמיד לסוגי ערכים משונים
    items = []
    for k, v in features.items():
        if v is None:
            continue
        try:
            items.append(f"{k}={v}")
        except Exception:
            items.append(f"{k}=[unserializable]")
    summary = ", ".join(items)

    return {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": "Crypto futures analyst. Concise, structured."},
            {"role": "user", "content": f"Symbol={sym}\nFeatures={summary}"},
        ],
        "temperature": 0.2,
        "max_tokens": 350,
    }


async def analyze_with_ai(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    מחזיר: {"ok": bool, "analysis": str}
    - אם אין מפתח API: חוזר עם ok=False וניתוח מינימלי.
    - אם quality נמוך מאוד ואין קונפליקט קולות: מדלגים (חיסכון בעלויות/לטנסי).
    """
    if not OPENAI_API_KEY:
        return {"ok": False, "analysis": "[AI disabled]"}

    # איכות: קודם quality_score; אם חסר – ננסה final_prob (0..1) * 10 כדי להתאים לסקאלת 0..10
    q_raw = features.get("quality_score")
    if q_raw is None:
        q_raw = (_to_float_safe(features.get("final_prob"), 0.0) * 10.0)
    q = _to_float_safe(q_raw, 0.0)

    conflict = _to_float_safe(features.get("vote_conflict"), 0.0)

    if q < AI_MIN_QUALITY and conflict < AI_CONFLICT_MIN:
        return {"ok": False, "analysis": "[AI skipped] below thresholds"}

    async with _sema:
        try:
            payload = _build(features)
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT) as x:
                r = await x.post(f"{OPENAI_BASE_URL}/chat/completions", headers=headers, json=payload)
                r.raise_for_status()
                data = r.json()
                # תומך במבנה הוותיק של chat.completions
                msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
                txt = (msg.get("content") or "").strip()
                return {"ok": True, "analysis": txt or "[AI empty]"}
        except Exception as e:
            return {"ok": False, "analysis": f"[AI error: {e}]"}


# -------- NEW: analyze_with_ai_and_filter --------
async def analyze_with_ai_and_filter(
    *,
    symbols: List[str],
    interval: str,
    market: str,
    max_items: int = 10,
    run_early_approvals: bool = True,
) -> Dict[str, Any]:
    """
    מחזיר מבנה:
      {
        "accepted": [ {symbol, side, entry, sl, tp1, tp2?, tp3?, leverage, success_pct, reason} ... ],
        "rejected": [ {symbol, reason} ... ]
      }
    סינון Placeholder — שמרני ופשוט כדי שהראוטים ירוצו חלק. אפשר להקשיח בעתיד.
    """
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for s in symbols[: max(0, int(max_items))]:
        su = str(s).upper().strip()
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













































