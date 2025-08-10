web: gunicorn main:app -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:${PORT:-8000} --timeout 120 --graceful-timeout 30 --keep-alive 5
















