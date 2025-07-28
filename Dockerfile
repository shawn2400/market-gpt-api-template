
# שלב בסיסי: Python רזה
FROM python:3.11-slim

# משתנים לסביבת עבודה נקייה ולוגים ישירים
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# התקנת תלות מערכת לבניית ספריות כבדות כמו ta-lib, Prophet וכו'
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    libffi-dev \
    libatlas-base-dev \
    libprotobuf-dev \
    libpng-dev \
    libjpeg-dev \
    libopenblas-dev \
    liblapack-dev \
    gfortran \
    git \
    curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# הגדרת תיקיית עבודה
WORKDIR /app

# העתקת קובץ הדרישות בלבד קודם – יאפשר cache טוב
COPY requirements.txt .

# פתרון לקריסה של pystan: התקנה מוקדמת של numpy ו-cython
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir numpy cython

# התקנת כל הדרישות
RUN pip install --no-cache-dir -r requirements.txt

# העתקת שאר קבצי הקוד
COPY . .

# פתיחת פורט (חשוב ב־Render ודומיו)
EXPOSE 5000

# הפעלת Gunicorn (שרת WSGI לפרודקשן)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "main:app"]











