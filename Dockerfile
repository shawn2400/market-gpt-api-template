# Dockerfile

FROM python:3.11-slim

# === משתני סביבה לשיפור ביצועים וניקיון
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100

# === התקנות בסיסיות
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl libssl-dev libffi-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# === יצירת תיקייה
WORKDIR /app

# === העתקת דרישות והתקנת תלויות
COPY requirements.txt .
RUN pip install -r requirements.txt

# === העתקת קוד המקור
COPY . .

# === פתיחת פורט
EXPOSE 5000

# === הרצת Gunicorn עם Uvicorn Worker
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "300"]






