# Dockerfile לפרויקט AlgoGPT עם תמיכה מלאה ב־matplotlib, pandas, ו־TA
FROM python:3.11-slim

# מניעת קבצי bytecode + הדפסת לוגים מיד
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# התקנת ספריות מערכת נדרשות עבור pandas, numpy, TA-Lib, matplotlib ועוד
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc build-essential libpq-dev libssl-dev libffi-dev \
    libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev \
    libblas-dev liblapack-dev libatlas-base-dev gfortran \
    libfreetype6-dev libpng-dev libopenblas-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# הגדרת תיקיית עבודה
WORKDIR /app

# התקנת תלויות פייתון
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# העתקת כל קבצי הפרויקט
COPY . .

# הפעלת FastAPI עם Gunicorn ו־Uvicorn Worker
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "90"]










