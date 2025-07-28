FROM python:3.11-slim

# התקנות בסיסיות
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libffi-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# תיקיית עבודה
WORKDIR /app

# העתקת קבצים
COPY requirements.txt .
COPY main.py .

# התקנת כל התלויות
RUN pip install --no-cache-dir -r requirements.txt

# חשיפת פורטים
EXPOSE 8080
EXPOSE 5000

# הפעלת שני השירותים (Flask + Aiohttp) דרך main.py
CMD ["python", "main.py"]









