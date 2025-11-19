# 🚀 AlgoGPT MetaBrain v9.1 - Staged Deployment Guide

## Overview
This deployment implements **full automation** with **zero manual intervention**. The system automatically progresses through 3 staged phases based on health metrics, with built-in Auto-Repair and Self-Healing systems.

---

## ✅ What's New in This Deployment

### 1. **Trailing TP Early Exit Fix** ✅
- **Fixed:** Positions closing too early (before TP2/TP3)
- **Changes:**
  - Activation threshold: 25% → **50%** (activates later)
  - Trailing distance: 15% → **10%** (tighter stop)
- **Result:** Trades can now reach TP2/TP3 with 45% exit percentages

### 2. **Stage Engine System** 🎯
Auto-progression through 3 deployment stages:

#### **Stage 1: Stable-Health Monitoring** (24-48h)
- Focus: System stability verification
- Auto-Run: ❌ Disabled
- Auto-Trading: ❌ Disabled
- Duration: 24-48 hours (configurable)
- Promotion Criteria: GREEN health + stable metrics

#### **Stage 2: Full Auto Trading (Validation)** (6-12h)
- Focus: 100% Dynamic Automatic Trading with monitoring
- Auto-Run: ✅ Enabled (30 symbols pool)
- Auto-Trading: ✅ **FULLY ENABLED** (100% automatic, zero manual approval)
- Duration: 6-12 hours
- Promotion Criteria: Low errors + stable execution

#### **Stage 3: Full Auto Trading** 🚀
- Focus: Autonomous operation
- Auto-Run: ✅ Enabled (full pool)
- Auto-Trading: ✅ Enabled (zero intervention)
- Auto-Promotion: Permanent (no further stages)

### 3. **Auto-Repair System** 🛠️
Automatically detects and fixes common issues:
- Redis disconnections → auto-reconnect
- Binance client errors → auto-reload
- WebSocket failures → auto-restart
- **Exponential backoff:** 1s → 2s → 5s → 10s → 30s
- **Max attempts:** 3 (then triggers freeze)

### 4. **Self-Healing System** 🔥
Ultimate recovery mechanism:
- Monitors `/readyz` endpoint every 5 minutes
- **Trigger:** 5 consecutive failures
- **Action:** Freeze system (safe recovery)
- **Cooldown:** 30 minutes between recovery attempts

---

## 📋 Required Environment Variables

### **Stage Engine Configuration**
```bash
# Core Settings
STAGE_ENGINE_ENABLE=1                  # Enable Stage Engine (1=yes, 0=no)
STAGE_AUTO_PROMOTE=1                   # Auto-promote between stages
STAGE_AUTO_FREEZE=1                    # Auto-freeze on critical errors
STAGE_HEALTH_INTERVAL=60               # Health check interval (seconds)

# Stage Durations (optional - defaults below)
STAGE_1_UPTIME_HOURS=24                # Stage 1 minimum uptime (24-48h recommended)
STAGE_2_UPTIME_HOURS=12                # Stage 2 minimum uptime (12-24h recommended)
```

### **Auto-Repair Configuration**
```bash
AUTO_REPAIR_ENABLE=0                   # Enable Auto-Repair (0=disabled by default)
AUTO_REPAIR_INTERVAL=60                # Check interval (seconds)
AUTO_REPAIR_MAX_ATTEMPTS=3             # Max repair attempts before freeze
```

### **Self-Healing Configuration**
```bash
SELF_HEALING_ENABLE=0                  # Enable Self-Healing (0=disabled by default)
SELF_HEALING_COOLDOWN=300              # Check cooldown (5 minutes)
SELF_HEALING_MAX_FAILURES=5            # Consecutive failures before freeze
```

---

## 🎯 Deployment Strategy (Render.com)

### **Phase 1: Deploy + Stage 1 (24-48h)**
**Goal:** Verify system stability

1. **Push to GitHub:**
   ```bash
   git add .
   git commit -m "Deploy MetaBrain v9.1 - Staged Auto-Deployment"
   git push origin main
   ```

2. **Render Auto-Deploy:**
   - Render detects GitHub push
   - Automatic build + deployment
   - Workflows restart automatically

3. **Set Environment Variables (Render Dashboard):**
   ```bash
   # Required (already set)
   BINANCE_API_KEY=<your_key>
   BINANCE_API_SECRET=<your_secret>
   TELEGRAM_BOT_TOKEN=<your_token>
   TELEGRAM_CHAT_ID=<your_chat_id>
   
   # New Variables (add these)
   STAGE_ENGINE_ENABLE=1
   STAGE_AUTO_PROMOTE=1
   STAGE_AUTO_FREEZE=1
   STAGE_1_UPTIME_HOURS=24
   STAGE_2_UPTIME_HOURS=12
   ```

4. **Monitor Stage 1 (24-48h):**
   - Check Telegram: `/stage_status`
   - Verify health: GREEN status
   - Watch metrics: CPU, RAM, Redis, BanShield
   - Expected: **No trading**, just monitoring

5. **Auto-Promotion to Stage 2:**
   - System auto-promotes after 24h of GREEN health
   - Telegram notification sent automatically
   - No manual intervention required

### **Phase 2: Stage 2 (6-12h)**
**Goal:** 100% Automatic Trading with validation

1. **Monitor Stage 2:**
   - Auto-Run: **Enabled** (medium pool - 30 symbols)
   - Auto-Trading: ✅ **FULLY ENABLED** (100% automatic - zero manual approval)
   - Check `/stage_status` daily
   - Verify: Low error count (<3 in 10m)
   - **Trades execute automatically** - no intervention needed!

2. **Auto-Promotion to Stage 3:**
   - System auto-promotes after 6h of stable Stage 2
   - Telegram notification sent automatically
   - **Full pool activated** (30 → 50 symbols)

### **Phase 3: Stage 3 (Full Auto - Maximum Performance)**
**Goal:** Maximum autonomous trading performance

1. **Full Automation Active:**
   - Auto-Run: ✅ Enabled (full pool - 50 symbols)
   - Auto-Trading: ✅ Enabled (100% automatic - zero intervention)
   - Multi-Target TP: ✅ Active (TP1/TP2/TP3)
   - Trailing TP: ✅ Activates at 50% profit (dynamic per trade)
   - Dynamic SL/TP: ✅ All protection layers active (base defaults)

2. **Monitoring:**
   - Telegram reports every 10 minutes
   - Use `/stage_status` anytime
   - System auto-freezes on critical errors
   - **4-10 high-quality trades per day** expected

---

## 📱 Telegram Commands

### **Stage Management**
```
/stage_status      - Show current stage + health metrics
/stage_promote     - Manual promotion (emergency override)
/stage_freeze      - Freeze system (stop auto-trading)
/stage_unfreeze    - Unfreeze system (resume)
/stage_logs        - Show last 20 stage history events
```

### **Expected Flow**
1. **Deploy** → Stage 1 (4h) - Health monitoring only
2. **Auto-promote** → Stage 2 (6h) - **100% AUTO TRADING** (30 symbols)
3. **Auto-promote** → Stage 3 (permanent) - Maximum performance (50 symbols)

---

## 🛡️ Safety Mechanisms

### **Auto-Freeze Triggers**
System automatically freezes on:
- ❌ **RED health** for 3 consecutive checks (3 minutes)
- ❌ **Auto-Repair failure** after 3 attempts
- ❌ **Self-Healing failure** after 5 consecutive failures
- ❌ **WebSocket disconnected** for 10+ minutes
- ❌ **BanShield RED zone** persistent

### **Manual Freeze**
Use `/stage_freeze` anytime to stop auto-trading:
- Prevents auto-promotion
- Disables auto-trading
- Requires `/stage_unfreeze` to resume

---

## 🔧 Troubleshooting

### **Problem: Stage stuck in Stage 1**
**Cause:** Health not GREEN for full uptime period

**Solution:**
1. Check `/stage_status` for issues
2. Resolve health problems (Redis, CPU, RAM, etc.)
3. Wait for GREEN health + full uptime
4. Manual promote: `/stage_promote` (if needed)

### **Problem: System frozen**
**Cause:** Auto-freeze triggered by critical error

**Solution:**
1. Check `/stage_status` for freeze reason
2. Investigate root cause (Telegram logs)
3. Fix underlying issue
4. Unfreeze: `/stage_unfreeze`

### **Problem: Trades closing before TP2/TP3**
**Cause:** Old Trailing TP activation settings

**Solution:**
- ✅ **Already fixed** in this deployment
- Activation: 50% profit (was 25%)
- Distance: 10% trailing (was 15%)
- TP2/TP3 can now execute (45% each)

---

## 📊 Expected Timeline

| Stage | Duration | Auto-Run | Auto-Trading | Key Activity |
|-------|----------|----------|--------------|--------------|
| **1** | 4h | ❌ | ❌ | Health monitoring |
| **2** | 6h | ✅ (30 symbols) | ✅ **100% AUTO** | Dynamic automatic trading |
| **3** | Permanent | ✅ (50 symbols) | ✅ **100% AUTO** | Maximum performance |

**Total time to full automation:** 10-12 hours (not 36-72h!)**

---

## ✅ Verification Checklist (Before Deploy)

- [ ] All ENV variables set in Render dashboard
- [ ] GitHub repo synced (latest commit pushed)
- [ ] Render auto-deploy configured (GitHub integration)
- [ ] Telegram bot token + chat ID verified
- [ ] Binance API keys active + funded account ($174.52+)
- [ ] N8N_WEBHOOK_SECRET configured (production safety)
- [ ] All background workers enabled (9 workflows)

---

## 🎉 Post-Deployment

### **First 4 Hours** (Stage 1)
- Monitor Telegram for stage status updates
- Verify `/stage_status` shows Stage 1
- Check health metrics: CPU, RAM, Redis, BanShield
- **No trading expected** - just monitoring

### **4-10 Hours** (Stage 2)
- Auto-promotion to Stage 2 (Telegram notification)
- **100% automatic trading activated!** 🚀
- 30 symbols pool - zero manual approval needed
- Verify error rates low (<3 in 10m)
- **Expect 2-6 automatic trades** in this phase

### **10+ Hours** (Stage 3)
- Auto-promotion to Stage 3 (Telegram notification)
- **Maximum performance activated** 🎯
- 50 symbols pool - full automation
- 4-10 high-quality trades per day
- Multi-Target TP system active (TP1/TP2/TP3)
- Trailing TP activates at 50% profit (dynamic per trade)
- All base protection layers active (SL/TP defaults)

---

## 📝 Notes

- **Production database:** Automatic via Neon (Render integration)
- **Zero downtime:** Render handles rolling deploys
- **Auto-recovery:** Stage Engine + Auto-Repair + Self-Healing
- **Manual override:** Telegram commands available anytime
- **Rollback:** GitHub + Render allow instant rollback if needed

---

## 🚨 Emergency Contacts

**System Issues:**
- Use `/stage_freeze` to stop trading
- Check logs: `/stage_logs`
- Contact: Telegram admin (@your_admin)

**Manual Override:**
- Freeze: `/stage_freeze`
- Unfreeze: `/stage_unfreeze`
- Force promote: `/stage_promote`

---

**Good luck with your deployment! 🚀**
