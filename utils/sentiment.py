# utils/sentiment.py
from __future__ import annotations
from typing import Dict, Any
from utils.news_utils import fetch_crypto_news, analyze_news_impact

def summarize_sentiment() -> Dict[str, Any]:
    news = fetch_crypto_news(public=True)
    scored = analyze_news_impact(news)
    if not scored:
        return {"ok": True, "score": 0.0, "buckets": {}, "samples": 0}

    pos = sum(1 for x in scored if x["impact_score"] > 0)
    neg = sum(1 for x in scored if x["impact_score"] < 0)
    neu = sum(1 for x in scored if x["impact_score"] == 0)
    total = max(1, pos + neg + neu)
    # מיפוי פשוט ל־(-100..100)
    score = 100.0 * (pos - neg) / total
    return {
        "ok": True,
        "score": round(score, 2),
        "buckets": {"positive": pos, "negative": neg, "neutral": neu},
        "samples": total,
    }

