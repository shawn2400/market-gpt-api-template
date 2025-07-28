FROM python:3.11-slim

WORKDIR /app
COPY scan_futures.py .
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8080
CMD ["python", "scan_futures.py"]







