# שלב בסיסי: Python רזה
FROM python:3.11-slim

# משתנים לסביבת עבודה נקייה ולוגים ישירים
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# התקנת תלות מערכת לבניית ספריות כבדות כמו prophet ו־ta
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

# שלב ביניים: התקנת numpy ו־cython תחילה כדי למנוע שגיאות בבניית Prophet
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir numpy cython \
    && pip install --no-cache-dir -r requirements.txt

# העתקת כל הקוד
COPY . .

# פתיחת פורט (Render מחפש את זה)
EXPOSE 5000

# הפעלת uvicorn (FastAPI) במקום gunicorn של Flask
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]












