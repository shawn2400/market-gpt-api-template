# CI/CD Setup Guide

Continuous Integration and Continuous Deployment pipeline for AlgoGPT.

## Table of Contents

1. [Overview](#overview)
2. [GitHub Actions Setup](#github-actions-setup)
3. [Testing Pipeline](#testing-pipeline)
4. [Deployment Pipeline](#deployment-pipeline)
5. [Monitoring & Alerts](#monitoring--alerts)

---

## Overview

AlgoGPT uses **GitHub Actions** for CI/CD with the following stages:

```
Commit → Test → Build → Deploy → Monitor
```

**Goals:**
- Automated testing on every commit
- Automated deployment to staging/production
- Zero-downtime deployments
- Rollback capability
- Performance monitoring

---

## GitHub Actions Setup

### 1. Create Workflow Directory

```bash
mkdir -p .github/workflows
```

### 2. Main CI/CD Workflow

Create `.github/workflows/main.yml`:

```yaml
name: AlgoGPT CI/CD

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

env:
  PYTHON_VERSION: '3.11'
  NODE_VERSION: '20'

jobs:
  test:
    name: Run Tests
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      
      - name: Cache dependencies
        uses: actions/cache@v3
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-cov pytest-asyncio
      
      - name: Run linter
        run: |
          pip install flake8
          flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
      
      - name: Run type checker
        run: |
          pip install mypy
          mypy utils/ workers/ --ignore-missing-imports || true
      
      - name: Run tests
        run: |
          pytest tests/ -v --cov=utils --cov=workers --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
          fail_ci_if_error: false
  
  security-scan:
    name: Security Scan
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v3
      
      - name: Run Bandit (Python security)
        run: |
          pip install bandit
          bandit -r utils/ workers/ -f json -o bandit-report.json || true
      
      - name: Check for secrets
        run: |
          pip install detect-secrets
          detect-secrets scan --all-files --force-use-all-plugins
  
  build:
    name: Build & Package
    needs: [test, security-scan]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v3
      
      - name: Build Docker image (if applicable)
        run: |
          docker build -t algogpt:${{ github.sha }} .
      
      - name: Push to registry
        run: |
          echo "${{ secrets.DOCKER_PASSWORD }}" | docker login -u "${{ secrets.DOCKER_USERNAME }}" --password-stdin
          docker push algogpt:${{ github.sha }}
  
  deploy-staging:
    name: Deploy to Staging
    needs: build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/develop'
    environment: staging
    
    steps:
      - name: Deploy to staging
        run: |
          curl -X POST ${{ secrets.STAGING_DEPLOY_WEBHOOK }} \
            -H "Authorization: Bearer ${{ secrets.DEPLOY_TOKEN }}" \
            -d '{"version": "${{ github.sha }}"}'
      
      - name: Run smoke tests
        run: |
          sleep 30
          curl -f https://staging.algogpt.com/health || exit 1
  
  deploy-production:
    name: Deploy to Production
    needs: build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    environment: production
    
    steps:
      - name: Deploy to production
        run: |
          curl -X POST ${{ secrets.PROD_DEPLOY_WEBHOOK }} \
            -H "Authorization: Bearer ${{ secrets.DEPLOY_TOKEN }}" \
            -d '{"version": "${{ github.sha }}"}'
      
      - name: Run smoke tests
        run: |
          sleep 30
          curl -f https://algogpt.com/health || exit 1
      
      - name: Notify Telegram
        if: success()
        run: |
          curl -X POST "https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage" \
            -d "chat_id=${{ secrets.TELEGRAM_CHAT_ID }}" \
            -d "text=✅ AlgoGPT deployed to production (commit: ${{ github.sha }})"
```

---

## Testing Pipeline

### Unit Tests Structure

Create `tests/` directory:

```bash
tests/
├── __init__.py
├── conftest.py
├── test_market_intelligence.py
├── test_multi_tf_manager.py
├── test_quality_score.py
└── test_performance_tracker.py
```

### Example Test File

`tests/test_multi_tf_manager.py`:

```python
import pytest
from utils.multi_tf_manager import MultiTFContextManager

@pytest.fixture
def tf_manager():
    return MultiTFContextManager()

def test_multi_tf_context_creation(tf_manager):
    """Test multi-TF context manager initialization"""
    assert tf_manager is not None
    assert hasattr(tf_manager, 'get_contexts')

@pytest.mark.asyncio
async def test_get_multi_tf_contexts(tf_manager):
    """Test fetching multi-TF contexts"""
    contexts = await tf_manager.get_contexts(
        symbol="BTCUSDT",
        intervals=["15m", "1h", "4h"]
    )
    
    assert contexts is not None
    assert "15m" in contexts
    assert "1h" in contexts
    assert "4h" in contexts

def test_tf_cache(tf_manager):
    """Test TF caching mechanism"""
    # First call - should fetch
    # Second call - should use cache
    pass
```

### pytest.ini Configuration

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto
addopts = -v --cov=utils --cov=workers --cov-report=html
```

---

## Deployment Pipeline

### Zero-Downtime Deployment

Create `scripts/deploy.sh`:

```bash
#!/bin/bash
# Zero-downtime deployment script

set -e

VERSION=$1
ENVIRONMENT=${2:-production}

echo "🚀 Deploying AlgoGPT ${VERSION} to ${ENVIRONMENT}..."

# 1. Health check before deployment
echo "📊 Pre-deployment health check..."
curl -f https://${ENVIRONMENT}.algogpt.com/health || exit 1

# 2. Pull latest code
echo "📥 Pulling latest code..."
git fetch origin
git checkout ${VERSION}

# 3. Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt --quiet

# 4. Run database migrations
echo "🗄️ Running database migrations..."
python scripts/migrate.py

# 5. Restart workers (rolling restart)
echo "🔄 Restarting workers..."
for worker in auto_scanner position_monitor n8n_bridge; do
    echo "  Restarting ${worker}..."
    pkill -f "workers/${worker}.py" || true
    sleep 2
    nohup python "workers/${worker}.py" > "/tmp/logs/${worker}.log" 2>&1 &
    sleep 5
done

# 6. Restart main server
echo "🔄 Restarting main server..."
pkill -f "gunicorn" || true
sleep 2
gunicorn -c gunicorn_conf.py main:app &
sleep 10

# 7. Post-deployment health check
echo "📊 Post-deployment health check..."
for i in {1..10}; do
    if curl -f https://${ENVIRONMENT}.algogpt.com/health; then
        echo "✅ Deployment successful!"
        exit 0
    fi
    echo "  Attempt $i/10 failed, retrying..."
    sleep 5
done

echo "❌ Deployment failed!"
exit 1
```

### Rollback Script

Create `scripts/rollback.sh`:

```bash
#!/bin/bash
# Rollback to previous version

set -e

echo "⏪ Rolling back to previous version..."

# Get previous commit
PREVIOUS=$(git rev-parse HEAD~1)

# Deploy previous version
./scripts/deploy.sh ${PREVIOUS}

echo "✅ Rollback complete!"
```

---

## Monitoring & Alerts

### Health Check Endpoint

Already implemented at `/health`. Enhance with:

```python
# main.py
@app.get("/health/detailed")
async def health_detailed():
    """Detailed health check for monitoring"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": os.getenv("APP_VERSION", "unknown"),
        "uptime_seconds": time.time() - start_time,
        "workers": {
            "auto_scanner": check_worker_health("auto_scanner"),
            "position_monitor": check_worker_health("position_monitor"),
            "n8n_bridge": check_worker_health("n8n_bridge")
        },
        "database": check_database_health(),
        "external_apis": {
            "binance": check_binance_health(),
            "openai": check_openai_health()
        }
    }
```

### Prometheus Metrics

Create `routes/metrics.py`:

```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest

# Define metrics
trades_total = Counter('algogpt_trades_total', 'Total trades', ['status'])
pnl_total = Gauge('algogpt_pnl_total_usd', 'Total PnL in USD')
worker_cycle_time = Histogram('algogpt_worker_cycle_seconds', 'Worker cycle time')

@router.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type="text/plain")
```

### Grafana Dashboard

Create `configs/grafana_dashboard.json` with panels for:
- Trade volume
- Win rate trend
- PnL over time
- Worker performance
- API latency

---

## Environment-Specific Configs

### Staging

`.env.staging`:
```bash
# Staging environment
ENV=staging
DEBUG=1
LOG_LEVEL=DEBUG

# Use paper trading
EXECUTE_TRADES=0

# Reduced limits
MAX_DAILY_TRADES=5
MAX_TRADE_BUDGET=50
```

### Production

`.env.production`:
```bash
# Production environment
ENV=production
DEBUG=0
LOG_LEVEL=INFO

# Live trading
EXECUTE_TRADES=1

# Normal limits
MAX_DAILY_TRADES=20
MAX_TRADE_BUDGET=500
```

---

## Best Practices

1. **Always test in staging first**
2. **Use feature flags** for gradual rollouts
3. **Monitor metrics** during deployment
4. **Have rollback plan** ready
5. **Automate everything** possible

---

**Last Updated:** November 2, 2025  
**Version:** 1.0.0  
**Maintained by:** AlgoGPT Team
