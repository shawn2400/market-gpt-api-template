# utils/news_utils.py
from __future__ import annotations
from typing import List, Dict, Any, Optional
import os, time, re
import requests

__all__ = ["fetch_crypto_news", "analyze_news_impact"]

_CP_BASE = "https://cryptopanic.com/api/v1/posts/"

_S = requests.Session()
_S.trust_env = False
_S.headers.update({
    "User-Agent": "AlgoGPT/2 news",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})

def _get_json(url: str, params: Dict[str, Any], timeout: float = 10.0) -> Optional[dict]:
    try:
        r = _S.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def fetch_crypto_news(
    silent_on_missing_key: bool = True,
    filter: str = "",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    שולף ידיעות מ־CryptoPanic.
    - אם חסר מפתח: מחזיר [] אם silent_on_missing_key=True, אחרת זורק Exception.
    - filter אפשרי (אופציונלי): hot / rising / important / bullish / bearish
    """
    token = os.getenv("CRYPTO_PANIC_API_KEY") or os.getenv("CRYPTOPANIC_API_KEY") or ""
    if not token:
        if silent_on_missing_key:
            return []
        raise RuntimeError("Missing CRYPTO_PANIC_API_KEY")

    params = {
        "auth_token": token,
        "kind": "news",              # רק כתבות (לא media)
        "public": "true",
        "page": 1,
        "currencies": "",            # אפשר להוסיף "BTC,ETH" אם רוצים פילטור
        "filter": filter or "",
    }

    data = _get_json(_CP_BASE, params=params) or {}
    results = data.get("results") or []
    items: List[Dict[str, Any]] = []

    for it in results[: int(limit)]:
        try:
            votes = it.get("votes") or {}
            currencies = [c.get("code") for c in (it.get("currencies") or []) if c.get("code")]
            items.append({
                "title": it.get("title"),
                "url": it.get("url"),
                "source": it.get("domain"),
                "published_at": it.get("published_at"),
                "currencies": currencies,
                "votes": {
                    "up": votes.get("positive") or votes.get("liked") or 0,
                    "down": votes.get("negative") or 0,
                    "important": votes.get("important") or 0,
                },
                "metadata": {
                    "id": it.get("id"),
                    "slug": it.get("slug"),
                    "filter": filter or "",
                },
            })
        except Exception:
            continue

    return items

# ---------- אימפקט/סנטימנט פשוטים (היוריסטיקה) ----------

_NEG_WORDS = re.compile(r"\b(hack|exploit|plunge|dump|ban|lawsuit|shutdown|halt|bankrupt|scam|fraud|breach)\b", re.I)
_POS_WORDS = re.compile(r"\b(pump|surge|rally|approve|approval|etf|partnership|upgrade|integrat(e|ion)|record)\b", re.I)

def _sentiment_from_title(title: str) -> str:
    if not title:
        return "neutral"
    if _NEG_WORDS.search(title):
        return "bearish"
    if _POS_WORDS.search(title):
        return "bullish"
    return "neutral"

def analyze_news_impact(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    מוסיף לכל ידיעה:
      - sentiment: bullish/bearish/neutral (לפי מילים בכותרת)
      - impact_score: 0..100 (היוריסטיקה פשוטה: important/votes/מקור/מילות מפתח)
    """
    out: List[Dict[str, Any]] = []
    trusted_sources = {
        "coindesk.com", "cointelegraph.com", "theblock.co",
        "reuters.com", "bloomberg.com", "wsj.com"
    }

    for it in items:
        title = (it.get("title") or "").strip()
        src = (it.get("source") or "").strip().lower()
        votes = it.get("votes") or {}
        imp = int(votes.get("important") or 0)
        up  = int(votes.get("up") or 0)
        down = int(votes.get("down") or 0)

        sentiment = _sentiment_from_title(title)

        score = 20  # בסיס
        score += min(imp * 10, 30)           # important מצביע על אימפקט
        score += min(max(up - down, 0) * 2, 20)
        if src in trusted_sources:
            score += 10
        if sentiment == "bullish":
            score += 10
        elif sentiment == "bearish":
            score += 10
        score = max(0, min(100, score))

        o = dict(it)
        o["sentiment"] = sentiment
        o["impact_score"] = score
        out.append(o)

    # סדר יורד לפי אימפקט
    out.sort(key=lambda x: int(x.get("impact_score", 0)), reverse=True)
    return out










