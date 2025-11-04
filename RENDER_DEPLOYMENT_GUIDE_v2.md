# 🚀 AlgoGPT Render Deployment Guide (Using Replit Database)

## Overview

Deploy AlgoGPT to Render **without extra database costs** by using your existing Replit PostgreSQL database.

**Total Cost: $25/month** 🎉

### Architecture:
- ✅ **Render Web Service** ($25/month) - Runs AlgoGPT + all workers
- ✅ **Replit PostgreSQL** (FREE) - Your existing database
- ✅ **Auto-deployment** from GitHub

---

## 📋 Prerequisites

1. ✅ **Render Account** with $25/month plan
2. ✅ **GitHub Repository** 
3. ✅ **Replit Database** (what you have now)
4. ✅ **All API Keys** ready

---

## 🎯 Step-by-Step Deployment

### Step 1: Get Replit Database URL

1. **In Replit, open Shell and run:**
   ```bash
   echo $DATABASE_URL
   ```

2. **Copy the output** - it looks like:
   ```
   postgresql://username:password@host:port/database
   ```

3. **Save this URL** - you'll need it for Render!

---

### Step 2: Push Code to GitHub

```bash
git add .
git commit -m "Prepare for Render deployment"
git push origin main
```

**Verify these files exist:**
- ✅ `render-simple.yaml`
- ✅ `start.sh`
- ✅ `requirements.txt`
- ✅ `gunicorn_conf.py`

---

### Step 3: Create Render Web Service

1. **Go to:** https://dashboard.render.com

2. **Click:** "New +" → "Web Service"

3. **Connect GitHub repository**

4. **Configure:**
   - **Name:** `algogpt-production`
   - **Region:** Oregon (or closest to you)
   - **Branch:** `main`
   - **Runtime:** Python 3
   - **Build Command:**
     ```bash
     pip install --upgrade pip && pip install -r requirements.txt && chmod +x start.sh
     ```
   - **Start Command:**
     ```bash
     ./start.sh
     ```
   - **Plan:** Starter ($25/month)

5. **Click:** "Create Web Service" (DON'T deploy yet!)

---

### Step 4: Add Environment Variables

**Go to:** Environment tab in your Render service

**Add these secrets:**

#### Critical Secrets (REQUIRED):
```bash
# Database (from Step 1)
DATABASE_URL=postgresql://your-replit-db-url-here

# Binance
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret

# Telegram
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
TELEGRAM_ADMIN_IDS=your_telegram_user_id

# OpenAI
OPENAI_API_KEY=your_openai_api_key

# X.AI (Grok)
XAI_API_KEY=your_xai_api_key

# N8N
N8N_WEBHOOK_SECRET=your_n8n_webhook_secret

# Security Tokens
OPS_SIGN_SECRET=your_long_random_secret_32_chars
WEBHOOK_HMAC_SECRET=your_long_random_secret_32_chars
API_BEARER_TOKEN=your_long_random_token
PRIMARY_API_TOKEN=your_long_random_token
ALGOGPT_TOKENS=your_long_random_token
AI_MESH_SECRET=your_long_random_secret

# Render
RENDER_API_KEY=your_render_api_key
```

**Click:** "Save Changes"

---

### Step 5: Deploy!

Render will automatically deploy after saving environment variables.

**Monitor logs:**
```
📦 Installing Python dependencies...
🔧 Making scripts executable...
✅ Build complete!
🚀 Starting AlgoGPT Production System...
✅ Database URL configured
📡 Starting background workers...
  → Auto Health Monitor
  → Auto Scanner
  → Daily Digest
  → GPT-5 Orchestrator
  → GitHub Auto-Commit
  → Heartbeat Monitor
  → N8N Bridge
  → Position Monitor
  → Sentinel Security
✅ All 9 background workers started
🌐 Starting Gunicorn server on port 10000...
```

---

### Step 6: Verify Deployment

1. **Get your Render URL:**
   - Example: `https://algogpt-production.onrender.com`

2. **Test health endpoint:**
   ```bash
   curl https://algogpt-production.onrender.com/health
   ```

   Expected: `{"status":"ok"}`

3. **Check Telegram:**
   - You should receive startup notification

---

### Step 7: Configure Replit Database Access (Important!)

**Replit PostgreSQL needs to allow external connections:**

1. **In Replit, check if database allows external IPs:**
   - By default, Replit PostgreSQL is accessible from anywhere
   - No firewall configuration needed! ✅

2. **If connection fails, check:**
   - DATABASE_URL format is correct
   - No typos in connection string
   - Database is active in Replit

---

### Step 8: Set Up Auto-Deployment

**Already configured!** 

**How it works:**
```
Replit (develop) 
   ↓ (GitHub Auto-Commit every 10 minutes)
GitHub (main branch)
   ↓ (Render Auto-Deploy)
Render (production)
```

**Timeline:**
- You make changes in Replit
- After 10 minutes: Auto-commit to GitHub
- After 2-3 minutes: Render redeploys
- **Total: ~13 minutes from code to production**

---

## 🔍 Troubleshooting

### Issue: "DATABASE_URL not set" error

**Solution:**
1. Verify DATABASE_URL is in Render environment variables
2. Check the URL format: `postgresql://user:pass@host:port/db`
3. Make sure there are no extra spaces

### Issue: "Connection refused" to database

**Solution:**
1. Verify Replit database is running (check Replit dashboard)
2. Test connection from Replit first:
   ```bash
   psql $DATABASE_URL -c "SELECT 1;"
   ```
3. Check if DATABASE_URL includes correct host/port

### Issue: Workers not starting

**Solution:**
1. Check Render logs for specific errors
2. Verify all worker files exist in `workers/` directory
3. Check `start.sh` has execute permissions

### Issue: Gunicorn timeout

**Solution:**
Add to environment variables:
```bash
GUNICORN_TIMEOUT=600
```

---

## 📊 Monitoring

### Health Checks

```bash
# Basic health
curl https://your-url.onrender.com/health

# Detailed health
curl https://your-url.onrender.com/health/detailed

# System info (requires API key)
curl -H "X-API-Key: YOUR_KEY" https://your-url.onrender.com/api/info
```

### Telegram Alerts

- Auto Health Monitor: Every 30 seconds
- Critical issues: Immediate notifications
- Trade proposals: Real-time

---

## 🔄 Development Workflow

### Daily Workflow:

1. **Morning:** Check Render logs + Telegram alerts
2. **Development:** Work in Replit as usual
3. **Auto-sync:** GitHub Auto-Commit every 10 minutes
4. **Auto-deploy:** Render updates automatically
5. **Monitoring:** Telegram notifications keep you informed

### Making Changes:

1. Edit code in Replit
2. Test locally (workflows running)
3. Wait 10 minutes for auto-commit
4. Wait 2-3 minutes for Render redeploy
5. Verify in production via Telegram alerts

---

## 💰 Cost Summary

| Service | Cost | Notes |
|---------|------|-------|
| Render Web Service | $25/month | Includes all workers |
| Replit PostgreSQL | **FREE** | Your existing database |
| SSL Certificate | **FREE** | Auto from Render |
| **TOTAL** | **$25/month** | 🎉 |

**Savings vs. Render PostgreSQL:** $7/month = $84/year!

---

## ✅ Final Checklist

Before going live:

- [ ] DATABASE_URL copied from Replit
- [ ] All environment variables set in Render
- [ ] Deployment successful (check logs)
- [ ] Health endpoint returns 200 OK
- [ ] All 9 workers running
- [ ] Telegram notifications working
- [ ] Binance API connected
- [ ] OpenAI API working
- [ ] GitHub auto-commit enabled (10 min interval)
- [ ] Test a few API calls

---

## 🎉 Success!

Once everything is running:

✅ **Production on Render at $25/month**  
✅ **Database stays on Replit (FREE)**  
✅ **Auto-deployment from Replit → GitHub → Render**  
✅ **Full monitoring via Telegram**  
✅ **Zero data migration needed**  

**Your AlgoGPT is now running 24/7 on production! 🚀**

---

## 🆘 Need Help?

**Check in order:**
1. Render deployment logs
2. Telegram alerts
3. Health endpoint response
4. Replit database status
5. Environment variables

**Common fixes:**
- Restart Render service (Settings → Manual Deploy)
- Verify DATABASE_URL format
- Check all API keys are valid
- Review GitHub Auto-Commit worker logs

---

**Created:** November 4, 2025  
**Version:** 2.0 (Replit Database)  
**Status:** ✅ Production Ready
