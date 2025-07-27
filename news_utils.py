import requests
import smtplib
from email.message import EmailMessage
import os
from dotenv import load_dotenv

load_dotenv()

# ✅ שליפת חדשות מ-CryptoPanic
def fetch_crypto_news():
    api_key = os.getenv("CRYPTO_PANIC_API_KEY")
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={api_key}&public=true"
    response = requests.get(url)
    response.raise_for_status()
    return response.json().get("results", [])

# ✅ ניתוח השפעת החדשות (מורחב לפי מילות מפתח)
def analyze_news_impact(news_list):
    scored_news = []
    for item in news_list:
        score = 0
        title = item.get("title", "").lower()

        positive_words = ["bullish", "surge", "breakout", "pump", "rally", "gain", "soar"]
        negative_words = ["bearish", "crash", "fud", "dump", "selloff", "collapse"]

        if any(word in title for word in positive_words):
            score += 1
        if any(word in title for word in negative_words):
            score -= 1

        scored_news.append({
            "title": item.get("title"),
            "published_at": item.get("published_at"),
            "url": item.get("url"),
            "impact_score": score
        })
    return scored_news

# ✅ שליחת מייל עם או בלי קובץ מצורף
def send_email_alert(subject, body="See attached.", attachment=None):
    try:
        EMAIL_ADDRESS = os.getenv("ALERT_EMAIL_ADDRESS", "your_email@example.com")
        EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD", "your_password")
        TO_EMAIL = os.getenv("ALERT_TO_EMAIL", EMAIL_ADDRESS)

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = TO_EMAIL
        msg.set_content(body)

        if attachment:
            msg.add_attachment(
                attachment,
                maintype="application",
                subtype="pdf",
                filename="report.pdf"
            )

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
    except Exception as e:
        print(f"[!] Email failed: {e}")




