FROM python:3.11-slim as base

# הגדרות סביבה
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# התקנות בסיסיות בלבד
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

# העתקת קובץ הדרישות והתקנת תלויות
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# העתקת כל הקוד כולל תיקיות routes/, utils/, static/
COPY . .

# בדיקה אם התיקייה routes קיימת – למניעת קריסה
RUN test -d routes || (echo "❌ תיקיית routes חסרה!" && exit 1)

# הפעלת השרת
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "300"]






















