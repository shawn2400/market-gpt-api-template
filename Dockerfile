FROM python:3.11-slim

# התקנת תלות מערכת
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libffi-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# הגדרת תיקיית עבודה
WORKDIR /app

# העתקת קבצים והתקנת דרישות
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# העתקת הקוד עצמו
COPY . .

# פתיחת פורט האפליקציה (רק Flask)
EXPOSE 5000

# הרצת Flask באמצעות gunicorn להרצה יציבה ותקינה (פרודקשן)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "main:app"]










