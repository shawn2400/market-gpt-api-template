# Dockerfile להרצת אפליקציית aiohttp
FROM python:3.11

WORKDIR /app
COPY . /app

RUN pip install aiohttp numpy

EXPOSE 8080
CMD ["python", "scan_futures.py"]





