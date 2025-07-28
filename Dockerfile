FROM python:3.11-slim

# התקנות בסיסיות
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libffi-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# תיקיית עבודה
WORKDIR /app

# העתקת קבצים
COPY requirements.txt .
COPY utils/scan_futures.py ./scan_futures.py
COPY app/flask_api.py ./flask_api.py  # דוגמה לקובץ Flask אם יש

# התקנת כל הספריות
RUN pip install --no-cache-dir -r requirements.txt

# חשיפת פורטים (ניתן להריץ שני שירותים שונים אם צריך)
EXPOSE 8080
EXPOSE 5000

# פקודת ברירת מחדל – להריץ aiohttp בלבד
CMD ["python", "scan_futures.py"]









