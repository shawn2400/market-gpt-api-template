# ====== Config ======
REG        ?= ghcr.io/your-org
IMAGE      ?= algogpt
TAG        ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo latest)
PLATFORMS  ?= linux/amd64
PORT       ?= 10000
WEB_CONCURRENCY ?= 2
GUNICORN_TIMEOUT ?= 120

# Docker build cache (אופציונלי)
BUILDX_CACHE_NS ?= $(REG)/$(IMAGE)
CACHE_FROM ?= type=registry,ref=$(BUILDX_CACHE_NS):buildcache
CACHE_TO   ?= type=registry,ref=$(BUILDX_CACHE_NS):buildcache,mode=max

# ====== Helpers ======
SHELL := /bin/bash
.ONESHELL:
.SILENT: help
.PHONY: help venv install lint format test run stop logs sh build buildx push release clean health smoke

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
	echo "  health         - curl /health_full"
	echo "  smoke          - scripts/smoke.sh (מומלץ אחרי דפלוי)"
	echo "  clean          - remove dangling images"

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
