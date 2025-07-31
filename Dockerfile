# 🐍 בסיס רזה לפייתון 3.11
FROM python:3.11-slim

# ✅ הגדרות סביבת ריצה
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# ✅ עדכון מערכת והתקנת תלותים בסיסיים
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc curl libpq-dev libffi-dev libssl-dev git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ✅ הגדרת תיקיית עבודה
WORKDIR /app

# ✅ התקנת דרישות
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ✅ העתקת כל הקוד
COPY . .

# ✅ הפעלת Gunicorn עם UvicornWorker
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "300"]





