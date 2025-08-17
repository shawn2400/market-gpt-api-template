# utils/sentiment.py
from __future__ import annotations
from typing import Dict, Any
from utils.news_utils import fetch_crypto_news, analyze_news_impact

def sentiment_summary() -> Dict[str, Any]:
    news = fetch_crypto_news(public=True)
    scored = analyze_news_impact(news)
    pos = sum(1 for n in scored if n["impact_score"] > 0)
    neg = sum(1 for n in scored if n["impact_score"] < 0)
    neu = sum(1 for n in scored if n["impact_score"] == 0)
    total = max(1, pos + neg + neu)
    score = (pos - neg) / total * 100.0  # -100..100
    return {
        "ok": True,
        "score": round(score, 2),
        "buckets": {"positive": pos, "negative": neg, "neutral": neu},
        "samples": total
    }

