# Autonomous AI Agents Setup Guide

## Overview
AlgoGPT includes 4 optional AI agent workers that provide advanced automation and optimization capabilities. These workers are **OPTIONAL** and can be enabled individually based on your needs and infrastructure capacity.

## Available Agents

### 1. GPT Orchestrator (Master Coordinator)
**File:** `workers/gpt_orchestrator.py`
**Purpose:** Strategic decision-making and multi-agent coordination
**Requirements:** OpenAI API key (GPT-4o)
**Resource Impact:** Moderate (API calls every 30min)

**To Enable:**
```bash
# Add workflow (optional - for automatic startup)
# Or run manually:
python workers/gpt_orchestrator.py
```

**Environment Variables:**
- `ORCHESTRATOR_INTERVAL` - Decision interval in seconds (default: 1800 = 30min)

---

### 2. DeepSeek Optimizer
**File:** `workers/deepseek_optimizer.py`
**Purpose:** Trade optimization and refinement
**Requirements:** DeepSeek API key
**Resource Impact:** Low (processes tasks from queue)

**To Enable:**
```bash
python workers/deepseek_optimizer.py
```

**How it Works:**
- Listens to `trade_optimization_queue` in Redis
- Optimizes trade entry/exit points
- Stores results in `optimized_trades` queue

---

### 3. AI-X Monitor (Grok)
**File:** `workers/aix_monitor.py`
**Purpose:** Advanced system monitoring and anomaly detection
**Requirements:** xAI API key (AIX_SUPERVISOR_TOKEN or XAI_API_KEY)
**Resource Impact:** Low-Moderate

**To Enable:**
```bash
python workers/aix_monitor.py
```

**Environment Variables:**
- `AIX_PING_INTERVAL` - Health ping interval (default: 600 = 10min)
- `AIX_ANOMALY_CHECK` - Anomaly check interval (default: 120 = 2min)

---

### 4. Replit Agent Bridge
**File:** `workers/replit_agent_bridge.py`
**Purpose:** Integration with Replit Agent for autonomous operations
**Requirements:** None (uses local communication)
**Resource Impact:** Very Low

**To Enable:**
```bash
export REPLIT_AGENT_ENABLED=true
python workers/replit_agent_bridge.py
```

**Environment Variables:**
- `REPLIT_AGENT_ENABLED` - Enable/disable bridge (default: false)
- `BRIDGE_STATUS_INTERVAL` - Status report interval (default: 300 = 5min)

---

## Redis Queue System

### Local Fallback Mode
If Redis is unavailable, the system automatically falls back to in-memory queues and caching. This ensures:
- ✅ Tasks are still queued (in memory)
- ✅ Cache still works (in memory)
- ✅ No data loss for current session
- ⚠️ Data NOT persistent across restarts

### Redis Setup (Optional)
To enable Redis for persistent queuing:

1. **Local Development:**
   ```bash
   # Install Redis (not available on Replit)
   sudo apt-get install redis-server
   redis-server
   ```

2. **Production (Docker):**
   ```yaml
   # In docker-compose.yml
   redis:
     image: redis:7-alpine
     restart: always
   ```

3. **Set Environment:**
   ```bash
   export REDIS_URL=redis://localhost:6379/0
   ```

---

## Resource Considerations

### Current Replit Environment
- **CPU:** 1 vCPU (shared)
- **Memory:** 2GB RAM
- **Running Workflows:** 4 active

### Recommendations
1. **Minimal Setup (Current):**
   - ✅ Core Trading Engine
   - ✅ Auto Scanner
   - ✅ Heartbeat Monitor
   - ✅ Daily Health Report

2. **Light Enhancement (+GPT Orchestrator):**
   - Add GPT Orchestrator for strategic decisions
   - Impact: +10-15% CPU, +100MB RAM
   - Benefit: Better trade coordination

3. **Medium Enhancement (+DeepSeek):**
   - Add DeepSeek Optimizer
   - Impact: +5-10% CPU, +50MB RAM
   - Benefit: Optimized entry/exit points

4. **Full Stack (All Agents):**
   - Enable all 4 agents
   - Impact: +30-40% CPU, +200MB RAM
   - Benefit: Complete autonomous operation
   - ⚠️ May require upgrade to higher Replit plan

---

## Monitoring Agent Status

### Check if Agents are Running
```bash
# List Python processes
ps aux | grep "workers/"

# Check specific agent
ps aux | grep "gpt_orchestrator"
```

### View Agent Logs
```bash
# GPT Orchestrator
tail -f /tmp/logs/gpt_orchestrator.log

# DeepSeek Optimizer
tail -f /tmp/logs/deepseek_optimizer.log
```

### Redis Queue Status
```python
from utils.redis_queue import redis_queue

# Get queue length
length = redis_queue.queue_length('trade_optimization_queue')

# Peek at tasks
tasks = redis_queue.peek_queue('optimized_trades', count=5)

# Get Redis stats
stats = redis_queue.get_stats()
print(stats)
```

---

## Troubleshooting

### Agent Won't Start
1. Check API keys are set
2. Verify Python dependencies installed
3. Check Redis connectivity (if using)

### High CPU/Memory Usage
1. Increase intervals between operations
2. Disable non-critical agents
3. Consider upgrading Replit plan

### Redis Connection Errors
Don't worry! System automatically falls back to in-memory mode.
To fix permanently:
1. Ensure Redis is running
2. Check REDIS_URL environment variable
3. Verify network connectivity

---

## Production Deployment

For production with full agent stack:

1. **Use Docker Compose** (see `scripts/deploy_phase2_docker.sh`)
2. **Dedicated Redis instance**
3. **Sufficient resources** (2+ vCPU, 4GB+ RAM)
4. **Enable all agents** in docker-compose

**Current Setup:**
- ✅ Render.com (production ready)
- ✅ 4 core workflows active
- ⏸️ Optional agents available but not active
- 📝 Enable agents as needed based on performance

---

## Summary

✅ **Currently Active:** Core trading + monitoring
⏸️ **Available to Enable:** 4 AI agent workers
🔧 **Recommendation:** Start with GPT Orchestrator first, add others as needed
📊 **Monitor:** CPU/Memory usage before enabling all agents
