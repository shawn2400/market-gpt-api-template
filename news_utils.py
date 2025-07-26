import requests

CRYPTO_PANIC_API_KEY = "your_crypto_panic_api_key_here"  # החלף במפתח האמיתי שלך

NEWS_API_URL = "https://cryptopanic.com/api/v1/posts/"


def fetch_crypto_news():
    params = {
        "auth_token": CRYPTO_PANIC_API_KEY,
        "filter": "important",
        "public": "true",
        "kind": "news"
    }
    try:
        response = requests.get(NEWS_API_URL, params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])
    except Exception as e:
        print(f"[ERROR] Failed to fetch news: {e}")
        return []


def analyze_news_impact(news_items):
    positive_keywords = ["bullish", "surge", "rally", "partnership", "adoption", "approval"]
    negative_keywords = ["hack", "ban", "lawsuit", "regulation", "crash", "scam"]

    scored_news = []
    for item in news_items:
        score = 0
        title = item.get("title", "").lower()
        url = item.get("url", "")
        if any(word in title for word in positive_keywords):
            score += 1
        if any(word in title for word in negative_keywords):
            score -= 1
        scored_news.append({"title": item.get("title"), "url": url, "impact_score": score})

    return scored_news


# דוגמה לשימוש:
if __name__ == "__main__":
    news = fetch_crypto_news()
    analyzed = analyze_news_impact(news)
    for n in analyzed:
        print(f"{n['impact_score']} | {n['title']}\n{n['url']}\n")
