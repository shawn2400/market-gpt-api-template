# 📦 Image בסיס – Python 3.11 גרסה רזה
FROM python:3.11-slim

# ⚙️ משתני סביבה מומלצים
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# 📂 יצירת תיקיית עבודה
WORKDIR /app

# 📄 התקנת תלותים
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 📂 העתקת כל הפרויקט
COPY . .

# 🚀 הרצת Gunicorn עם Uvicorn Worker
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:5000", "--timeout", "300"]




