# בסיס על Python 3.10 (לא לשנות!)
FROM python:3.10-slim

# התקנת חבילות מערכת נדרשות (ל־prophet, numpy, pandas וכו')
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

# יצירת תיקיית עבודה
WORKDIR /app

# העתקת קבצי הפרויקט
COPY . .

# התקנת התלויות מ־requirements.txt
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# חשיפת פורט להפעלה
EXPOSE 10000

# הפעלת השרת עם Gunicorn
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:10000", "--timeout", "300"]


