# 🤖 AlgoGPT Autonomous Network - Phase 1

## Overview
The Autonomous Network is a self-monitoring, self-healing system that ensures AlgoGPT runs 24/7 without manual intervention.

## Components

### 1. Daily Health Report 📊
**File:** `workers/daily_health_report.py`

**What it does:**
- Sends comprehensive system health report to Telegram at 23:00 daily
- Includes CPU, Memory, Disk usage, Uptime, Service status
- Lists all active components and their status

**To activate in Render:**
Add Background Worker:
- Name: `daily-health-report`
- Build Command: (leave empty)
- Start Command: `python workers/daily_health_report.py`

---

### 2. System Heartbeat Monitor 🫀
**File:** `workers/system_heartbeat.py`

**What it does:**
- Checks service health every 10 minutes
- Sends Telegram alerts only on failures (no spam)
- Auto-recovery detection and notification
- Critical alerts after 5 consecutive failures

**To activate in Render:**
Add Background Worker:
- Name: `heartbeat-monitor`
- Build Command: (leave empty)
- Start Command: `python workers/system_heartbeat.py`

**Environment Variables:**
```bash
HEARTBEAT_INTERVAL=600  # 10 minutes (in seconds)
BASE_URL=https://algogpt-docker.onrender.com
```

---

### 3. System Orchestrator 🤖
**File:** `config/system_orchestrator.json`

**What it is:**
- Configuration file mapping all AI agents and their roles
- Describes the entire system architecture
- Used for documentation and future automation

**Agents:**
- **core** - Main trading engine
- **gpt4** - AI analyst for trade proposals
- **market_intelligence** - Multi-TF market analysis
- **portfolio_intelligence** - Risk & exposure management
- **telegram** - Notifications and approvals
- **database** - PostgreSQL persistence
- **heartbeat_monitor** - Health monitoring
- **daily_reporter** - Daily reports

---

## How to Activate (Render.com)

### Step 1: Go to Render Dashboard
```
https://dashboard.render.com
```

### Step 2: Select your service
Click on **algogpt-docker**

### Step 3: Add Background Workers

#### Option A: Via Dashboard UI
1. Click **"New Background Worker"** (or similar)
2. Fill in:
   - **Name:** `daily-health-report`
   - **Start Command:** `python workers/daily_health_report.py`
   - **Instance Type:** Free or Starter
3. Repeat for `heartbeat-monitor`

#### Option B: Via render.yaml (Recommended)
Add to your `render.yaml`:

```yaml
services:
  - type: web
    name: algogpt-docker
    # ... existing config ...

  - type: worker
    name: daily-health-report
    env: docker
    dockerfilePath: ./Dockerfile
    dockerCommand: python workers/daily_health_report.py
    envVars:
      - key: TELEGRAM_BOT_TOKEN
        sync: false
      - key: TELEGRAM_CHAT_ID
        sync: false

  - type: worker
    name: heartbeat-monitor
    env: docker
    dockerfilePath: ./Dockerfile
    dockerCommand: python workers/system_heartbeat.py
    envVars:
      - key: HEARTBEAT_INTERVAL
        value: 600
      - key: BASE_URL
        value: https://algogpt-docker.onrender.com
      - key: TELEGRAM_BOT_TOKEN
        sync: false
      - key: TELEGRAM_CHAT_ID
        sync: false
```

---

## Expected Telegram Notifications

### Daily Report (23:00)
```
📊 AlgoGPT Daily Health Report

🤖 System Status
🟢 Service: Healthy
⏱️ Uptime: 5d 12h 34m

💻 Resources
🧠 CPU: 12.5%
💾 Memory: 45.2% (921MB / 2048MB)
💿 Disk: 23.1%

🔧 Active Components
✅ Market Scanner (531 symbols)
✅ Multi-TF Analysis (15M/1H/4H)
✅ GRID Trading Engine
✅ FUTURES Trading Engine
✅ Telegram Approval System
✅ PostgreSQL Database
✅ Dynamic Position Management

📅 02/11/2025 23:00
🌍 Render.com - Frankfurt (EU Central)
```

### Heartbeat Alert (Only on issues)
```
⚠️ AlgoGPT Core Unresponsive
🧠 CPU: 85.2% | 💾 MEM: 92.1%
⏰ 14:35:22
```

### Recovery Alert
```
✅ AlgoGPT Recovered
🧠 CPU: 15.3% | 💾 MEM: 48.7%
⏰ 14:40:15
```

---

## Resilience Features

✅ **Auto-Restart** - Render automatically restarts failed services
✅ **Health Checks** - `/readyz` endpoint monitored by Render
✅ **Failure Alerts** - Telegram notifications on consecutive failures
✅ **Recovery Detection** - Automatic notification when service recovers
✅ **Daily Reports** - Proactive health monitoring
✅ **Independent Workers** - Each component runs separately
✅ **Data Persistence** - PostgreSQL ensures no data loss

---

## Cost

- **Web Service:** $25/month (Standard plan)
- **Background Workers:** 
  - Free tier: 2 workers included
  - Paid: $7/month per worker

**Total for full setup:** $25-39/month

---

## Monitoring

Check system status:
```bash
curl https://algogpt-docker.onrender.com/readyz
```

View orchestrator config:
```bash
curl https://algogpt-docker.onrender.com/static/system_orchestrator.json
```

---

## Future Enhancements (Phase 2)

- [ ] Auto-scaling based on market volatility
- [ ] Multi-region failover
- [ ] Performance analytics dashboard
- [ ] Trade performance ML optimization
- [ ] Automated strategy adjustment based on results
