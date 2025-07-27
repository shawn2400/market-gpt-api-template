# בסיס על Python 3.10 בלבד
FROM python:3.10-slim

# התקנת תלות מערכת ל־prophet, numpy, pandas, fpdf ועוד
RUN apt-get update && apt-get install -y \
    build-essential \
    g++ \
    python3-dev \
    libatlas-base-dev \
    libffi-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    libopenblas-dev \
    curl \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# הגדרת תיקיית עבודה
WORKDIR /app

# העתקת הקבצים לתוך הקונטיינר
COPY . .

# התקנת ספריות פייתון
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# פתיחת פורט עבור Gunicorn
EXPOSE 10000

# הרצת האפליקציה דרך Gunicorn (מאוד מומלץ לפרודקשן)
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:10000", "--timeout", "300"]



