# בסיס קליל עם Python 3.11
FROM python:3.11-slim

# הגדרות סביבתיות
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# תיוג גרסה ותחזוקה
LABEL maintainer="AlgoGPT Team <dev@algogpt.ai>" \
      version="2.0.1" \
      description="AlgoGPT Docker Image for FastAPI Trading Bot"

# עדכון מערכת והתקנת תלויות בסיסיות
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libopenblas-dev \
    liblapack-dev \
    libjpeg-dev \
    libpng-dev \
    curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# תיקיית עבודה
WORKDIR /app

# העתקת קבצי תלויות והתקנתן
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
 && pip install --no-cache-dir cython numpy==1.26.4 \
 && pip install --no-cache-dir -r requirements.txt

# העתקת כל קוד המקור
COPY . .

# פתיחת פורט 5000
EXPOSE 5000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl --fail http://localhost:5000/ || exit 1

# הרצת Gunicorn עם uvicorn worker, 2 עובדים, timeout של 5 דקות
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "300"]


















