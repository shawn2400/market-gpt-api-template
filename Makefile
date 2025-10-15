# ====== Config ======
REG        ?= ghcr.io/your-org
IMAGE      ?= algogpt
TAG        ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo latest)
PLATFORMS  ?= linux/amd64
PORT       ?= 10000
WEB_CONCURRENCY ?= 2
GUNICORN_TIMEOUT ?= 120

# Ultra service base URL (override in CI/Local as needed)
ULTRA_HOST ?= https://algogpt-docker.onrender.com

# Security / Secrets (export in your shell or CI)
#   OPS_SIGN_SECRET  - HMAC secret for /ultra/ops/*
#   METRICS_BEARER   - Bearer required by /ultra/metrics
#   API_BEARER_TOKEN - Public API bearer for read-only GETs (if needed)
OPS_SIGN_SECRET ?=
METRICS_BEARER  ?=
API_BEARER_TOKEN ?=

# Docker build cache (optional)
BUILDX_CACHE_NS ?= $(REG)/$(IMAGE)
CACHE_FROM ?= type=registry,ref=$(BUILDX_CACHE_NS):buildcache
CACHE_TO   ?= type=registry,ref=$(BUILDX_CACHE_NS):buildcache,mode=max

# ====== Helpers ======
SHELL := /bin/bash
.ONESHELL:
.SILENT: help
.PHONY: help venv install lint format test run stop logs sh build buildx push release clean health smoke \
        run-docker \
        ultra-readyz ultra-readyz-strict ultra-meta ultra-version ultra-metrics \
        ultra-prefs ultra-reload ultra-sig ultra-ts ultra-health

help:
	echo "Targets:"
	echo "  venv           - create venv and install dev deps"
	echo "  install        - pip install -r requirements.txt"
	echo "  lint           - ruff + mypy (אם קיימים בקובץ req)"
	echo "  format         - ruff format / black (אם מותקן)"
	echo "  test           - pytest (אם קיים)"
	echo "  run            - run locally with uvicorn"
	echo "  stop           - stop local docker container"
	echo "  logs           - docker logs -f"
	echo "  sh             - docker shell into running container"
	echo "  build          - docker build (single-arch)"
	echo "  buildx         - docker buildx (multi-arch/cached)"
	echo "  push           - docker push $(REG)/$(IMAGE):$(TAG)"
	echo "  release        - buildx + push (tag)"
	echo "  run-docker     - run container locally with minimal env"
	echo "  health         - curl /health_full (fallback /health)"
	echo "  smoke          - scripts/smoke.sh (מומלץ אחרי דפלוי)"
	echo "  clean          - remove dangling images"
	echo "  --- Ultra ---"
	echo "  ultra-readyz          - GET $(ULTRA_HOST)/ultra/readyz"
	echo "  ultra-readyz-strict   - GET $(ULTRA_HOST)/ultra/readyz/strict"
	echo "  ultra-meta            - GET $(ULTRA_HOST)/ultra/meta"
	echo "  ultra-version         - GET $(ULTRA_HOST)/ultra/meta/version"
	echo "  ultra-metrics         - GET $(ULTRA_HOST)/ultra/metrics (Authorization: Bearer)"
	echo "  ultra-ts              - print epoch timestamp (sec)"
	echo "  ultra-sig             - make HMAC for body (env BODY) with OPS_SIGN_SECRET"
	echo "  ultra-prefs           - POST /ultra/ops/runtime/prefs with HMAC"
	echo "  ultra-reload          - POST /ultra/ops/policy/reload with HMAC"

# ====== Python local ======
venv:
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip setuptools wheel

install:
	[ -d .venv ] || $(MAKE) venv
	. .venv/bin/activate && pip install -r requirements.txt

lint:
	[ -d .venv ] || $(MAKE) venv
	. .venv/bin/activate && { ruff check . || true; } ; \
	{ mypy . || true; }

format:
	[ -d .venv ] || $(MAKE) venv
	. .venv/bin/activate && { ruff format . || true; } ; \
	{ black . || true; }

test:
	[ -d .venv ] || $(MAKE) venv
	. .venv/bin/activate && { pytest -q || true; }

run:
	export UVICORN_RELOAD=1 UVICORN_LOG_LEVEL=info
	python3 -m uvicorn main:app --host 0.0.0.0 --port $(PORT)

# ====== Docker ======
build:
	docker build -t $(REG)/$(IMAGE):$(TAG) .

buildx:
	docker buildx create --use --name algogpt_builder 2>/dev/null || true
	docker buildx build \
	  --platform $(PLATFORMS) \
	  --build-arg PORT=$(PORT) \
	  --tag $(REG)/$(IMAGE):$(TAG) \
	  --build-arg WEB_CONCURRENCY=$(WEB_CONCURRENCY) \
	  --build-arg GUNICORN_TIMEOUT=$(GUNICORN_TIMEOUT) \
	  --cache-from=$(CACHE_FROM) --cache-to=$(CACHE_TO) \
	  --push \
	  .

push:
	docker push $(REG)/$(IMAGE):$(TAG)

release: buildx

run-docker:
	docker run --rm -it \
	  -e PORT=$(PORT) \
	  -e WEB_CONCURRENCY=$(WEB_CONCURRENCY) \
	  -e GUNICORN_TIMEOUT=$(GUNICORN_TIMEOUT) \
	  -e API_BEARER_TOKEN=$${API_BEARER_TOKEN:-dev_token} \
	  -e OPS_SIGN_SECRET=$${OPS_SIGN_SECRET:-dev_secret} \
	  -e METRICS_BEARER=$${METRICS_BEARER:-dev_metrics} \
	  -e BINANCE_API_KEY=$${BINANCE_API_KEY:-} \
	  -e BINANCE_API_SECRET=$${BINANCE_API_SECRET:-} \
	  -p $(PORT):$(PORT) \
	  --name $(IMAGE) \
	  $(REG)/$(IMAGE):$(TAG)

stop:
	docker rm -f $(IMAGE) 2>/dev/null || true

logs:
	docker logs -f $(IMAGE)

sh:
	docker exec -it $(IMAGE) /bin/bash

health:
	curl -fsS "http://127.0.0.1:$(PORT)/health_full" | jq . || curl -fsS "http://127.0.0.1:$(PORT)/health" | jq .

smoke:
	bash scripts/smoke.sh "http://127.0.0.1:$(PORT)" "$${API_BEARER_TOKEN:-dev_token}"

clean:
	docker image prune -f

# ====== Ultra helpers ======
ultra-readyz:
	curl -fsS "$(ULTRA_HOST)/ultra/readyz" | jq .

ultra-readyz-strict:
	curl -fsS -o /dev/stderr -w "HTTP:%{http_code}\n" "$(ULTRA_HOST)/ultra/readyz/strict" | jq . || true

ultra-meta:
	curl -fsS "$(ULTRA_HOST)/ultra/meta" | jq .

ultra-version:
	curl -fsS "$(ULTRA_HOST)/ultra/meta/version" | jq .

ultra-metrics:
	test -n "$(METRICS_BEARER)" || { echo "METRICS_BEARER is empty"; exit 2; }
	curl -fsS -H "Authorization: Bearer $(METRICS_BEARER)" "$(ULTRA_HOST)/ultra/metrics" | head -n 20

ultra-ts:
	date +%s

# BODY env var must contain a compact JSON string (e.g. BODY='{"patch":{"TP_DYNAMIC_ENABLE":1}}')
ultra-sig:
	test -n "$(OPS_SIGN_SECRET)" || { echo "OPS_SIGN_SECRET is empty"; exit 2; }
	TS=$$(date +%s); \
	SIG=$$(python3 - <<'PY'
import os, hmac, hashlib, sys
sec = os.environ.get("OPS_SIGN_SECRET","")
ts  = os.environ.get("TS","")
body = os.environ.get("BODY","").encode("utf-8")
print(hmac.new(sec.encode("utf-8"), (ts.encode("utf-8")+b"."+body), hashlib.sha256).hexdigest())
PY
); \
	echo "TS=$$TS"; echo "SIG=$$SIG"

# Example:
#   make ultra-prefs BODY='{"patch":{"TP_DYNAMIC_ENABLE":1,"ENTRY_CONF_MIN":0.7}}'
ultra-prefs:
	test -n "$(OPS_SIGN_SECRET)" || { echo "OPS_SIGN_SECRET is empty"; exit 2; }
	test -n "$(BODY)" || { echo 'Please set BODY JSON, e.g. BODY='\''{"patch":{"TP_DYNAMIC_ENABLE":1}}'\'''; exit 2; }
	TS=$$(date +%s); \
	SIG=$$(TS="$$TS" BODY="$(BODY)" OPS_SIGN_SECRET="$(OPS_SIGN_SECRET)" python3 - <<'PY'
import os, hmac, hashlib
sec=os.environ["OPS_SIGN_SECRET"]; ts=os.environ["TS"]; body=os.environ["BODY"].encode("utf-8")
print(hmac.new(sec.encode("utf-8"), (ts.encode("utf-8")+b"."+body), hashlib.sha256).hexdigest())
PY
); \
	curl -fsS -X POST "$(ULTRA_HOST)/ultra/ops/runtime/prefs" \
	  -H "Content-Type: application/json" \
	  -H "X-Timestamp: $$TS" \
	  -H "X-Signature: $$SIG" \
	  -d '$(BODY)' | jq .

# No body => sign ts+'.' only
ultra-reload:
	test -n "$(OPS_SIGN_SECRET)" || { echo "OPS_SIGN_SECRET is empty"; exit 2; }
	TS=$$(date +%s); \
	SIG=$$(TS="$$TS" OPS_SIGN_SECRET="$(OPS_SIGN_SECRET)" python3 - <<'PY'
import os, hmac, hashlib
sec=os.environ["OPS_SIGN_SECRET"]; ts=os.environ["TS"]
print(hmac.new(sec.encode("utf-8"), (ts.encode("utf-8")+b"."), hashlib.sha256).hexdigest())
PY
); \
	curl -fsS -X POST "$(ULTRA_HOST)/ultra/ops/policy/reload" \
	  -H "X-Timestamp: $$TS" \
	  -H "X-Signature: $$SIG" | jq .

# Convenience alias to hit base /health on the Ultra app if exposed at /
ultra-health:
	curl -fsS "$(ULTRA_HOST)/health" | jq .

