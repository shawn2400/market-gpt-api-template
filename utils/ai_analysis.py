# utils/ai_analysis.py
from __future__ import annotations
import os, asyncio, httpx
from typing import Dict, Any, List, Tuple

OPENAI_API_KEY=(os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL=os.getenv("OPENAI_MODEL","gpt-4o")
OPENAI_BASE_URL=os.getenv("OPENAI_BASE_URL","https://api.openai.com/v1").rstrip("/")
OPENAI_TIMEOUT=float(os.getenv("OPENAI_TIMEOUT_SECONDS","30"))
OPENAI_MAX_CONCURRENCY=int(os.getenv("OPENAI_MAX_CONCURRENCY","4"))
AI_MIN_QUALITY=float(os.getenv("AI_MIN_QUALITY","8.5"))
AI_CONFLICT_MIN=float(os.getenv("AI_CONFLICT_MIN","0.2"))

_sema=asyncio.Semaphore(max(1,OPENAI_MAX_CONCURRENCY))

def _build(features:Dict[str,Any])->Dict[str,Any]:
    sym=features.get("symbol","?")
    summary=", ".join([f"{k}={v}" for k,v in features.items() if v is not None])
    return {"model":OPENAI_MODEL,
            "messages":[
                {"role":"system","content":"Crypto futures analyst. Concise, structured."},
                {"role":"user","content":f"Symbol={sym}\nFeatures={summary}"}
            ],
            "temperature":0.2,"max_tokens":350}

async def analyze_with_ai(features:Dict[str,Any])->Dict[str,Any]:
    if not OPENAI_API_KEY: return {"ok":False,"analysis":"[AI disabled]"}
    q=float(features.get("quality_score",0)); conflict=float(features.get("vote_conflict",0))
    if q<AI_MIN_QUALITY and conflict<AI_CONFLICT_MIN:
        return {"ok":False,"analysis":"[AI skipped] below thresholds"}
    async with _sema:
        try:
            async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT) as x:
                r=await x.post(f"{OPENAI_BASE_URL}/chat/completions",
                               headers={"Authorization":f"Bearer {OPENAI_API_KEY}"},
                               json=_build(features)); r.raise_for_status()
                data=r.json(); txt=(data.get("choices") or [{}])[0].get("message",{}).get("content","").strip()
                return {"ok":True,"analysis":txt or "[AI empty]"}
        except Exception as e: return {"ok":False,"analysis":f"[AI error: {e}]"}

# -------- NEW: analyze_with_ai_and_filter --------
async def analyze_with_ai_and_filter(
    *, symbols: List[str], interval: str, market: str, max_items: int = 10, run_early_approvals: bool = True
) -> Dict[str, Any]:
    """
    מחזיר מבנה:
      {
        "accepted": [ {symbol, side, entry, sl, tp1, tp2?, tp3?, leverage, success_pct, reason} ... ],
        "rejected": [ {symbol, reason} ... ]
      }
    הסינון כאן מינימלי (placeholder) כדי ליישר את הראוטים — אפשר להקשיח בהמשך.
    """
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    # פילטר דמה: לוקחים עד max_items, נותנים הנחות שמרניות
    for s in symbols[:max_items]:
        su = s.upper()
        try:
            # הנחות: LONG ברירת מחדל, SL=1.2% מהכניסה, TP1=1.8%
            # אפשר להחליף בלוגיקה אמיתית (quality_score, anchor וכו') אם זמין בהקשר.
            entry = None  # יתמלא בהמשך ע"י מקורות מחיר בראוט
            side = "LONG"
            leverage = 10
            tp1 = None
            sl = None
            success_pct = 0.55

            accepted.append({
                "symbol": su,
                "side": side,
                "entry": entry,   # יושלם downstream
                "sl": sl,
                "tp1": tp1,
                "leverage": leverage,
                "success_pct": success_pct,
                "reason": f"preliminary filter ({interval}/{market})"
            })
        except Exception as e:
            rejected.append({"symbol": su, "reason": f"filter_error: {e}"})

    return {"accepted": accepted, "rejected": rejected}















































