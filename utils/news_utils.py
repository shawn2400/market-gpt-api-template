# utils/news_utils.py
from __future__ import annotations

import os
import time
from typing import List, Dict, Any, Optional
import requests
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

CRYPTO_PANIC_API_KEY = os.getenv("CRYPTO_PANIC_API_KEY")
EMAIL_ADDRESS = os.getenv("ALERT_EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD")
TO_EMAIL = os.getenv("ALERT_TO_EMAIL", EMAIL_ADDRESS)

_SESSION = requests.Session()
_SESSION.trust_env = False
_SESSION.headers.update({
    "User-Agent": "AlgoGPT/2 news-utils",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})

def _get(url: str, timeout: float = 8.0) -> Optional[requests.Response]:
    try:
        r = _SESSION.get(url, timeout=timeout)
        if r.status_code == 200:
            return r
        # נסיון עדין להתגבר על עומסים זמניים
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(0.7)
            r2 = _SESSION.get(url, timeout=timeout)
            if r2.status_code == 200:
                return r2
        r.raise_for_status()
    except Exception as e:
        print(f"[news] http error: {e}")
    return None

def fetch_crypto_news(public: bool = True, filter_: str = "") -> List[Dict[str, Any]]:
    """
    מחלצת פוסטים מ־CryptoPanic. נדרש CRYPTO_PANIC_API_KEY ב־ENV.
    """
    try:
        if not CRYPTO_PANIC_API_KEY:
            raise ValueError("Missing CRYPTO_PANIC_API_KEY in environment")

        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTO_PANIC_API_KEY}&public={'true' if public else 'false'}"
        if filter_:
            url += f"&filter={filter_}"

        r = _get(url)
        if not r:
            return []
        data = r.json() or {}
        return list(data.get("results", []) or [])
    except Exception as e:
        print(f"[!] שגיאה בשליפת חדשות: {e}")
        return []

def analyze_news_impact(
    news_list: List[Dict[str, Any]],
    positive_words: Optional[List[str]] = None,
    negative_words: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    scored_news: List[Dict[str, Any]] = []
    seen_urls = set()

    default_positive = ["bullish", "surge", "breakout", "pump", "rally", "gain", "soar", "moon"]
    default_negative = ["bearish", "crash", "fud", "dump", "selloff", "collapse", "fear", "rekt"]

    positive_words = [w.lower() for w in (positive_words or default_positive)]
    negative_words = [w.lower() for w in (negative_words or default_negative)]

    for item in news_list:
        url = (item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        title = (item.get("title") or "").lower()
        desc = (item.get("description") or "").lower()
        text = f"{title} {desc}"

        score = 0
        if any(word in text for word in positive_words):
            score += 1
        if any(word in text for word in negative_words):
            score -= 1

        scored_news.append({
            "title": item.get("title"),
            "published_at": item.get("published_at"),
            "url": url,
            "impact_score": int(score),
            "source": item.get("source", {}),
            "currencies": item.get("currencies", []),
        })

    # סדר לפי השפעה ואז תאריך (אם קיים)
    scored_news.sort(key=lambda x: (x["impact_score"], x.get("published_at") or ""), reverse=True)
    return scored_news

def send_email_alert(subject: str, body: str = "See attached.", attachment: Optional[str | bytes] = None) -> bool:
    try:
        if not all([EMAIL_ADDRESS, EMAIL_PASSWORD, TO_EMAIL]):
            raise ValueError("Missing email credentials in environment")

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = TO_EMAIL
        msg.set_content(body)

        if attachment:
            if isinstance(attachment, bytes):
                msg.add_attachment(attachment, maintype="application", subtype="pdf", filename="report.pdf")
            elif isinstance(attachment, str) and os.path.exists(attachment):
                with open(attachment, "rb") as f:
                    file_data = f.read()
                msg.add_attachment(file_data, maintype="application", subtype="pdf", filename=os.path.basename(attachment))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)

        print("[+] Email sent successfully.")
        return True
    except Exception as e:
        print(f"[!] Email failed: {e}")
        return False

def get_latest_news() -> List[Dict[str, Any]]:
    return fetch_crypto_news()

def analyze_news_sentiment() -> Dict[str, Any]:
    news = fetch_crypto_news()
    scored = analyze_news_impact(news)
    return {"analyzed_news": scored}










