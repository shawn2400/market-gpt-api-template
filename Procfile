web: bash -lc "/app/prestart.sh && gunicorn -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-$(python - <<'PY'
import os, multiprocessing as mp
print(max(2, min(8, (mp.cpu_count() or 2) * 2)))
PY
)} -b 0.0.0.0:${PORT:-10000} main:app --timeout ${GUNICORN_TIMEOUT:-120}"


























