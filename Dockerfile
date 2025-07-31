FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libopenblas-dev liblapack-dev libjpeg-dev libpng-dev curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN echo "תוכן /app:" && ls -la /app
RUN echo "תוכן /app/routes:" && ls -la /app/routes || echo "תיקיית routes לא נמצאה"

# בדיקות קבצים (אל תכשל על הבדיקה, רק תציג)
RUN test -d /app/routes && echo "תיקיית routes קיימת" || echo "❌ תיקיית routes חסרה!"
RUN test -f /app/routes/ai.py && echo "routes/ai.py קיים" || echo "❌ הקובץ routes/ai.py לא קיים!"
RUN test -f /app/routes/__init__.py && echo "routes/__init__.py קיים" || echo "❌ הקובץ routes/__init__.py לא קיים!"

CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "300"]




