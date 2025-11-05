web: bash -lc "APP_MODULE=${APP_MODULE:-main:app}; \
  /app/prestart.sh 2>/dev/null || true; \
  gunicorn -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-$(python - <<'PY'
import os, multiprocessing as mp
print(max(2, min(8, (mp.cpu_count() or 2) * 2)))
PY
)} -b 0.0.0.0:${PORT:-10000} ${APP_MODULE} --timeout ${GUNICORN_TIMEOUT:-180} --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-45} --keep-alive ${GUNICORN_KEEPALIVE:-30}"

scanner: python workers/gpt_auto_suggest.py
health: python workers/auto_health_monitor.py
gpt5: python workers/gpt5_orchestrator.py
n8n: python workers/n8n_bridge.py
positions: python workers/position_monitor.py
sentinel: python workers/sentinel_security.py



























