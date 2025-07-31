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
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# הגדרת תיקיית עבודה
WORKDIR /app

# העתקת קובץ הדרישות והתקנת תלויות
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# העתקת כל הקוד כולל routes, utils וכו'
COPY . .

# ✅ בדיקה: האם routes/ai.py באמת קיים?
RUN echo "📁 תוכן תיקיית routes:" && ls -l /app/routes

# ✅ בדיקה נוספת (רק לפירוט): הדפס את כל הקבצים
RUN echo "🗂️ תוכן מלא של /app:" && ls -R /app

# הפעלת השרת
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "300"]























