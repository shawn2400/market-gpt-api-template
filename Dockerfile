FROM python:3.11-slim

# התקנת תלות מערכת
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libffi-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# הגדרת תיקיית עבודה
WORKDIR /app

# העתקת קבצים
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# פתיחת פורטים עבור Flask ו־AIOHTTP
EXPOSE 5000
EXPOSE 8080

# הרצת האפליקציה
CMD ["python", "main.py"]










