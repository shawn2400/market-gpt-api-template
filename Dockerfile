FROM python:3.11-slim as base

# הגדרות סביבת ריצה מומלצות
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# התקנות בסיסיות בלבד (ל־numpy, scipy, matplotlib)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas-dev liblapack-dev libjpeg-dev libpng-dev curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# יצירת תיקיית עבודה
WORKDIR /app

# התקנת התלויות
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# העתקת שאר הקבצים
COPY . .

# הפעלת השרת עם Gunicorn ו-UvicornWorker
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "300"]





















