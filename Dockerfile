FROM python:3.11-slim as base

# סביבת ריצה חכמה
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# התקנות מינימליות
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas-dev liblapack-dev libjpeg-dev libpng-dev curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# תיקייה ראשית
WORKDIR /app

# התקנת תלויות
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# העתקת כל הקוד
COPY . .

# הרצת Gunicorn עם uvicorn
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "300"]






















