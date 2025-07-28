FROM python:3.11-slim

# הגדרת תיקיית העבודה
WORKDIR /app

# העתקת קבצים
COPY requirements.txt .
COPY utils/scan_futures.py ./scan_futures.py

# התקנת תלויות
RUN pip install --no-cache-dir -r requirements.txt

# פתיחת פורט לשירות
EXPOSE 8080

# פקודת הרצה
CMD ["python", "scan_futures.py"]








