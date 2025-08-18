# utils/sentiment.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
import os

# מסתמכים על ספק החדשות והסקורינג שלך (שכבר קיימים אצלך)
try:
    from utils.news_utils import fetch_crypto_news, analyze_news_impact
except Exception as e:
    fetch_crypto_news = None  # type: ignore
    analyze_news_impact = None  # type: ignore

def _score_from_items(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not items:
        return {"ok": True, "score": 0.0, "buckets": {}, "samples": 0}

    pos = sum(1 for x in items if float(x.get("impact_score", 0)) > 0)
    neg = sum(1 for x in items if float(x.get("impact_score", 0)) < 0)
    neu = sum(1 for x in items if float(x.get("impact_score", 0)) == 0)
    total = max(1, pos + neg + neu)

    # מיפוי פשוט ל־(-100..100)
    score = 100.0 * (pos - neg) / float(total)

    return {
        "ok": True,
        "score": round(score, 2),
        "buckets": {"positive": pos, "negative": neg, "neutral": neu},
        "samples": total,
    }

def summary(filter: Optional[str] = None, max_items: int = 100) -> Dict[str, Any]:
    """
    מחזיר סיכום סנטימנט כולל ציון (-100..100).
    משתמש ב-CryptoPanic אם יש מפתח; אם אין – חוזר ניטרלי.
    """
    # תמיכה בשמות ENV נפוצים
    api_key = os.getenv("CRYPTO_PANIC_API_KEY") or os.getenv("CRYPTOPANIC_API_KEY") or ""

    # אם אין ספק/מפתח – תחזיר ניטרלי (לא נכשלת)
    if not fetch_crypto_news or not analyze_news_impact or not api_key:
        return {"ok": True, "score": 0.0, "buckets": {}, "samples": 0, "note": "news provider not configured"}

    try:
        # הפונקציה אצלך מקבלת (public: bool, filter: str)
        raw = fetch_crypto_news(public=True, filter=filter or "")
        scored = analyze_news_impact(raw)

        # חיתוך ל-top N אם צריך
        if isinstance(scored, list) and max_items and len(scored) > max_items:
            scored = scored[:max_items]

        res = _score_from_items(scored or [])
        # מידע עזר קטן
        res["note"] = f"source=CryptoPanic, items={res['samples']}"
        return res
    except Exception:
        # אם הספק קרס – תחזיר ניטרלי
        return {"ok": True, "score": 0.0, "buckets": {}, "samples": 0, "note": "sentiment: provider error"}

# תאימות לאחור לשם שהצגת
def summarize_sentiment(filter: Optional[str] = None, max_items: int = 100) -> Dict[str, Any]:
    return summary(filter=filter, max_items=max_items)


