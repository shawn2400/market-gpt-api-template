# שלב בסיס: Python 3.11 Slim
FROM python:3.11-slim

# הגדרות סביבת פיתוח מומלצות
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# התקנות בסיסיות (כדי למנוע בעיות עם pip או pandas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc build-essential libpq-dev libssl-dev libffi-dev libxml2-dev libxslt1-dev \
    libjpeg-dev zlib1g-dev libblas-dev liblapack-dev libatlas-base-dev gfortran \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# תיקיית העבודה באפליקציה
WORKDIR /app

# העתקת תלויות והתקנתן
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# העתקת שאר הקבצים
COPY . .

# הפעלת השרת עם Gunicorn + Uvicorn worker (FastAPI)
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "90"]









