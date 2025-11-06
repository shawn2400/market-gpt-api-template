#!/usr/bin/env bash
# Manual script to resume Neon endpoint
python - << 'PY'
from utils.neon_resume import ensure_neon_running
result = ensure_neon_running()
print(f"[{'OK' if result['ok'] else 'WARN'}] {result['message']}")
PY
