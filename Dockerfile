# Dockerfile להרצת אפליקציית aiohttp
FROM python:3.11-slim

# יצירת סביבת עבודה
WORKDIR /app

# העתקת קבצים
COPY scan_futures.py .

# התקנת ספריות בצורה יעילה
RUN pip install --no-cache-dir aiohttp numpy

# פתיחת פורט
EXPOSE 8080

# הפעלת השרת
CMD ["python", "scan_futures.py"]






