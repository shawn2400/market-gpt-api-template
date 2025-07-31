FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# תלויות מערכת שיכולות למנוע תקלות בעתיד
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# תיקיית עבודה
WORKDIR /app

# התקנת תלויות
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# העתקת שאר הקבצים
COPY . .

# הגדרת PYTHONPATH כדי לוודא שכל ה־import יעבדו
ENV PYTHONPATH="/app"

# הפעלת Gunicorn עם UvicornWorker
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:5000", "--timeout", "300"]


