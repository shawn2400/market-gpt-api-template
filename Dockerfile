# בסיס על Python 3.10 (לא 3.13!)
FROM python:3.10-slim

# עדכון בסיסי והתקנת ספריות הנדרשות ל־prophet ו־pandas
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
    && apt-get clean

# יצירת תיקיית עבודה
WORKDIR /app

# העתקת הקוד
COPY . .

# התקנת התלויות
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# פתיחת פורט
EXPOSE 10000

# הפעלת האפליקציה
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:10000"]

