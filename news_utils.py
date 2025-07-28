# news_utils.py

import requests
import smtplib
from email.message import EmailMessage
import os
from dotenv import load_dotenv

load_dotenv()

# ✅ שליפת חדשות מ־CryptoPanic עם טיפול שגיאות
def fetch_crypto_news():
    try:
        api_key = os.getenv("CRYPTO_PANIC_API_KEY")
        if not api_key:
            raise ValueError("Missing CRYPTO_PANIC_API_KEY in environment")

        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={api_key}&public=true"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json().get("results", [])
    except Exception as e:
        print(f"[!] שגיאה בשליפת חדשות: {e}")
        return []

# ✅ ניתוח השפעה לפי מילות מפתח חיוביות / שליליות
def analyze_news_impact(news_list):
    scored_news = []
    positive_words = ["bullish", "surge", "breakout", "pump", "rally", "gain", "soar"]
    negative_words = ["bearish", "crash", "fud", "dump", "selloff", "collapse", "fear"]

    for item in news_list:
        title = item.get("title", "").lower()
        score = 0

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

# ✅ שליחת מייל עם אפשרות לצרף קובץ PDF (בינארי)
def send_email_alert(subject, body="See attached.", attachment=None):
    try:
        EMAIL_ADDRESS = os.getenv("ALERT_EMAIL_ADDRESS")
        EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD")
        TO_EMAIL = os.getenv("ALERT_TO_EMAIL", EMAIL_ADDRESS)

        if not all([EMAIL_ADDRESS, EMAIL_PASSWORD, TO_EMAIL]):
            raise ValueError("Missing email credentials in environment variables")

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = TO_EMAIL
        msg.set_content(body)

        if attachment:
            if isinstance(attachment, bytes):
                msg.add_attachment(
                    attachment,
                    maintype="application",
                    subtype="pdf",
                    filename="report.pdf"
                )
            elif isinstance(attachment, str) and os.path.exists(attachment):
                with open(attachment, "rb") as f:
                    file_data = f.read()
                msg.add_attachment(
                    file_data,
                    maintype="application",
                    subtype="pdf",
                    filename=os.path.basename(attachment)
                )

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)

    except Exception as e:
        print(f"[!] Email failed: {e}")





