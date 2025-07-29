import requests
import smtplib
from email.message import EmailMessage
import os
from dotenv import load_dotenv

load_dotenv()

# === משתנים נדרשים מה־.env ===
CRYPTO_PANIC_API_KEY = os.getenv("CRYPTO_PANIC_API_KEY")
EMAIL_ADDRESS = os.getenv("ALERT_EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD")
TO_EMAIL = os.getenv("ALERT_TO_EMAIL", EMAIL_ADDRESS)


# ✅ שליפת חדשות מ־CryptoPanic
def fetch_crypto_news():
    try:
        if not CRYPTO_PANIC_API_KEY:
            raise ValueError("Missing CRYPTO_PANIC_API_KEY in environment")

        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTO_PANIC_API_KEY}&public=true"
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        return response.json().get("results", [])
    except Exception as e:
        print(f"[!] שגיאה בשליפת חדשות: {e}")
        return []


# ✅ ניתוח סנטימנט לפי מילים חיוביות/שליליות
def analyze_news_impact(news_list, positive_words=None, negative_words=None):
    scored_news = []
    seen_urls = set()

    default_positive = ["bullish", "surge", "breakout", "pump", "rally", "gain", "soar", "moon"]
    default_negative = ["bearish", "crash", "fud", "dump", "selloff", "collapse", "fear", "rekt"]

    positive_words = positive_words or default_positive
    negative_words = negative_words or default_negative

    for item in news_list:
        url = item.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        title = item.get("title", "").lower()
        desc = item.get("description", "").lower()
        text = title + " " + desc

        score = 0
        if any(word in text for word in positive_words):
            score += 1
        if any(word in text for word in negative_words):
            score -= 1

        scored_news.append({
            "title": item.get("title"),
            "published_at": item.get("published_at"),
            "url": url,
            "impact_score": score
        })

    return scored_news


# ✅ שליחת מייל (עם או בלי קובץ PDF)
def send_email_alert(subject, body="See attached.", attachment=None):
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

        print("[+] Email sent successfully.")

    except Exception as e:
        print(f"[!] Email failed: {e}")



















































































































































































