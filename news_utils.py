import requests

CRYPTO_PANIC_API_KEY = "89404de8e0bb4d6e78e95ed26ff19970cdb8830a"

def fetch_crypto_news():
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTO_PANIC_API_KEY}&public=true"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json().get("results", [])
    else:
        return []

def analyze_news_impact(news_items):
    scored_news = []
    for item in news_items:
        title = item.get("title", "")
        sentiment = item.get("votes", {})
        score = 0

        if "important" in title.lower() or "hack" in title.lower():
            score += 3
        if sentiment.get("positive", 0) > 3:
            score += 2
        if sentiment.get("negative", 0) > 2:
            score -= 2
        if "etf" in title.lower() or "approval" in title.lower():
            score += 2

        scored_news.append({
            "title": title,
            "url": item.get("url"),
            "published_at": item.get("published_at"),
            "score": score,
            "sentiment": sentiment,
        })

    return sorted(scored_news, key=lambda x: x["score"], reverse=True)

