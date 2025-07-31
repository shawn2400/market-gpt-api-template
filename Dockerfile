FROM python:3.11-slim

# ✅ משתנים חשובים – הגדרות סביבה
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ✅ מוודא שה-PYTHONPATH מוגדר כך ש-YOUR_MODULE יזוהה מכל מקום
ENV PYTHONPATH=/app

# ✅ תיקיית עבודה ראשית בתוך הקונטיינר
WORKDIR /app

# ✅ התקנת תלותים
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ✅ העתקת שאר הקבצים
COPY . .

# ✅ הפעלת השרת
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:5000", "--timeout", "300"]




