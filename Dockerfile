FROM python:3.11-slim as base

# === הגדרות סביבת פייתון ===
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# === התקנת חבילות מערכת חיוניות (מדעיות + curl) ===
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libopenblas-dev \
    liblapack-dev \
    libjpeg-dev \
    libpng-dev \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# === הגדרת תיקיית עבודה ===
WORKDIR /app

# === העתקת קובץ דרישות והתקנת תלויות ===
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# === העתקת כל שאר הקבצים לתוך התמונה ===
COPY . .

# === הדפסת תוכן תיקיית העבודה הראשית (לאבחון) ===
RUN echo "==== תוכן תיקיית העבודה הראשית (/app) ====" && ls -la

# === בדיקות קיום תיקיית routes וקבצים חיוניים ===
RUN test -d routes || (echo "❌ תיקיית routes חסרה!" && exit 1)
RUN test -f routes/ai.py || (echo "❌ הקובץ routes/ai.py לא קיים!" && exit 1)
RUN test -f routes/__init__.py || (echo "❌ הקובץ routes/__init__.py חסר!" && exit 1)

# === הדפסת תוכן תיקיית routes (לאבחון) ===
RUN echo "📁 תוכן תיקיית routes:" && ls -la routes

# === פקודת הרצת השרת FastAPI ב-Gunicorn עם UvicornWorker ===
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "300"]















