# בסיס - פייתון 3.11 slim
FROM python:3.11-slim as base

# הגדרות סביבת פייתון
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# התקנת חבילות מערכת חיוניות
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libopenblas-dev \
    liblapack-dev \
    libjpeg-dev \
    libpng-dev \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# הגדרת תיקיית עבודה
WORKDIR /app

# העתקת קובץ דרישות והתקנת התלויות
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# העתקת כל הקוד לתיקיית העבודה
COPY . .

# אבחון - הצגת תוכן תיקיית routes בתמונה
RUN echo "📁 תוכן תיקיית /app/routes:" && ls -la /app/routes

# בדיקה אם התיקייה קיימת
RUN test -d /app/routes || (echo "❌ תיקיית routes חסרה!" && exit 1)

# בדיקה אם הקבצים החשובים קיימים
RUN test -f /app/routes/ai.py || (echo "❌ הקובץ routes/ai.py לא קיים!" && exit 1)
RUN test -f /app/routes/__init__.py || (echo "❌ הקובץ routes/__init__.py חסר!" && exit 1)

# הפעלת השרת עם Gunicorn ו-UvicornWorker
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "300"]












