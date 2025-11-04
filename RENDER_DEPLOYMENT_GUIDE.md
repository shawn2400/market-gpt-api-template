# 🚀 AlgoGPT Render Deployment Guide

## Overview

This guide will help you deploy AlgoGPT to your $25/month Render server. The deployment includes:

- ✅ **Main AlgoGPT Server** (Gunicorn + FastAPI)
- ✅ **All 10 Background Workers** running in parallel
- ✅ **PostgreSQL Database** (installed on the same server - no extra cost!)
- ✅ **Auto-deployment** from GitHub
- ✅ **Full access from Replit** for continued development

---

## 📋 Prerequisites

Before you start, make sure you have:

1. ✅ **Render Account** with a $25/month plan
2. ✅ **GitHub Repository** with your AlgoGPT code
3. ✅ **All API Keys** ready (Binance, Telegram, OpenAI, etc.)
4. ✅ **Replit Database** (for migration)

---

## 🎯 Step-by-Step Deployment

### Step 1: Prepare Your GitHub Repository

1. **Push all code to GitHub:**
   ```bash
   git add .
   git commit -m "Prepare for Render deployment"
   git push origin main
   ```

2. **Verify these files exist in your repo:**
   - ✅ `render-simple.yaml` - Deployment configuration
   - ✅ `start.sh` - Startup script
   - ✅ `setup_db.sh` - PostgreSQL installation
   - ✅ `migrate_db.py` - Database migration tool
   - ✅ `.env.render.template` - Environment variables template
   - ✅ `requirements.txt` - Python dependencies
   - ✅ `gunicorn_conf.py` - Gunicorn configuration

---

### Step 2: Create Render Web Service

1. **Go to Render Dashboard:** https://dashboard.render.com

2. **Click "New +" → "Web Service"**

3. **Connect your GitHub repository:**
   - Select your AlgoGPT repository
   - Click "Connect"

4. **Configure the service:**
   - **Name:** `algogpt-production` (or your preferred name)
   - **Region:** Oregon (or closest to you)
   - **Branch:** `main`
   - **Root Directory:** Leave empty
   - **Runtime:** Python 3
   - **Build Command:** 
     ```bash
     pip install --upgrade pip && pip install -r requirements.txt && chmod +x start.sh setup_db.sh migrate_db.py && ./setup_db.sh
     ```
   - **Start Command:**
     ```bash
     ./start.sh
     ```
   - **Plan:** Starter ($25/month)

5. **Click "Create Web Service"**

---

### Step 3: Add Environment Variables

1. **Go to your service's "Environment" tab**

2. **Copy all secrets from `.env.render.template`:**

   ```bash
   # Critical Secrets (REQUIRED)
   BINANCE_API_KEY=your_binance_api_key
   BINANCE_API_SECRET=your_binance_api_secret
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token
   TELEGRAM_CHAT_ID=your_telegram_chat_id
   TELEGRAM_ADMIN_IDS=your_telegram_user_id
   OPENAI_API_KEY=your_openai_api_key
   XAI_API_KEY=your_xai_api_key
   N8N_WEBHOOK_SECRET=your_n8n_webhook_secret
   OPS_SIGN_SECRET=your_ops_sign_secret
   WEBHOOK_HMAC_SECRET=your_webhook_hmac_secret
   API_BEARER_TOKEN=your_api_bearer_token
   PRIMARY_API_TOKEN=your_primary_api_token
   ALGOGPT_TOKENS=your_algogpt_tokens
   AI_MESH_SECRET=your_ai_mesh_secret
   RENDER_API_KEY=your_render_api_key
   
   # Database (set after PostgreSQL installation)
   DATABASE_URL=postgresql://algogpt_user:algogpt_password_change_me@localhost/algogpt_production
   ```

3. **Click "Save Changes"**

   → Render will automatically redeploy with new environment variables

---

### Step 4: Wait for First Deployment

1. **Monitor the deployment logs:**
   - You'll see the build process
   - PostgreSQL installation
   - Dependencies installation

2. **Expected output:**
   ```
   📦 Installing Python dependencies...
   🔧 Making scripts executable...
   🗄️ Setting up PostgreSQL...
   ✅ Build complete!
   ```

3. **Once deployed, you'll see:**
   ```
   🚀 Starting AlgoGPT Production System...
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

### Step 5: Migrate Database from Replit

1. **From Replit, run the migration script:**

   ```bash
   # Set source database (Replit)
   export SOURCE_DATABASE_URL="$DATABASE_URL"
   
   # Set target database (Render)
   export TARGET_DATABASE_URL="postgresql://algogpt_user:algogpt_password_change_me@your-render-host/algogpt_production"
   
   # Run migration
   python migrate_db.py
   ```

2. **Expected output:**
   ```
   🗄️ AlgoGPT Database Migration
   📥 Source: postgresql://...
   📤 Target: postgresql://...
   🔌 Connecting to databases...
   🔍 Reflecting source database schema...
   📋 Creating target database schema...
   📊 Migrating tables...
     📦 slippage_history: copying 150 rows... ✅ Done!
     📦 breaker_state: copying 1 rows... ✅ Done!
     📦 market_states: copying 531 rows... ✅ Done!
     📦 audit_log: copying 1200 rows... ✅ Done!
     📦 ai_predictions: copying 500 rows... ✅ Done!
     📦 trade_outcomes: copying 200 rows... ✅ Done!
     📦 feedback_dataset: copying 300 rows... ✅ Done!
     📦 live_kpis: copying 50 rows... ✅ Done!
     📦 validation_runs: copying 10 rows... ✅ Done!
     📦 backtest_folds: copying 60 rows... ✅ Done!
   ✅ Migration complete! Migrated 3002 rows across 10 tables.
   ```

---

### Step 6: Verify Deployment

1. **Check your Render service URL:**
   - Example: `https://algogpt-production.onrender.com`

2. **Test the health endpoint:**
   ```bash
   curl https://algogpt-production.onrender.com/health
   ```

   Expected response:
   ```json
   {"status": "ok"}
   ```

3. **Check logs in Render dashboard:**
   - All 9 workers should be running
   - No errors in the logs
   - Telegram should receive startup notification

---

### Step 7: Configure Custom Domain (Optional)

1. **In Render Dashboard:**
   - Go to "Settings" → "Custom Domains"
   - Click "Add Custom Domain"
   - Enter your domain (e.g., `algogpt.yourdomain.com`)

2. **Update DNS records at your domain registrar:**
   - Add CNAME record pointing to your Render URL

3. **Wait for SSL certificate:**
   - Render auto-provisions Let's Encrypt SSL (free!)
   - Usually takes 5-10 minutes

---

### Step 8: Set Up Auto-Deployment

1. **Already configured!** The deployment uses `autoDeploy: true`

2. **How it works:**
   - Every time you push to GitHub `main` branch
   - Render automatically pulls latest code
   - Rebuilds and redeploys
   - Zero downtime deployment

3. **From Replit:**
   - Continue developing in Replit as normal
   - GitHub Auto-Commit worker pushes every 10 minutes
   - Render auto-deploys your changes

---

## 🔍 Troubleshooting

### Issue: PostgreSQL installation fails

**Solution:**
1. Check Render logs for specific error
2. Manually install PostgreSQL:
   ```bash
   sudo apt-get update
   sudo apt-get install -y postgresql postgresql-contrib
   sudo service postgresql start
   ```

### Issue: Workers not starting

**Solution:**
1. Check `start.sh` has execute permissions:
   ```bash
   chmod +x start.sh
   ```
2. Verify all worker files exist in `workers/` directory

### Issue: Database connection errors

**Solution:**
1. Verify `DATABASE_URL` is set correctly in environment variables
2. Check PostgreSQL service is running:
   ```bash
   sudo service postgresql status
   ```

### Issue: Gunicorn timeout errors

**Solution:**
1. Increase timeout in `render-simple.yaml`:
   ```yaml
   - key: GUNICORN_TIMEOUT
     value: 600  # Increase to 10 minutes
   ```

---

## 📊 Monitoring

### Check System Status

```bash
# Health check
curl https://your-render-url.onrender.com/health

# Detailed health
curl https://your-render-url.onrender.com/health/detailed

# System info (with API key)
curl -H "X-API-Key: YOUR_API_KEY" https://your-render-url.onrender.com/api/info
```

### View Logs

1. **Render Dashboard:**
   - Go to "Logs" tab
   - Real-time log streaming

2. **Telegram Alerts:**
   - Auto Health Monitor sends alerts every 30 seconds
   - Critical issues trigger immediate notifications

---

## 🔄 Continuous Development Workflow

### Replit → GitHub → Render

```
┌──────────────┐
│   Replit     │  ← You develop here
│  (Dev)       │
└──────┬───────┘
       │
       │ Auto-commit every 10 minutes
       ↓
┌──────────────┐
│   GitHub     │  ← Code repository
└──────┬───────┘
       │
       │ Auto-deploy on push
       ↓
┌──────────────┐
│   Render     │  ← Production server
│  ($25/month) │
└──────────────┘
```

### Workflow:

1. **Develop in Replit** (you have full access)
2. **GitHub Auto-Commit** pushes changes every 10 minutes
3. **Render Auto-Deploy** pulls and deploys automatically
4. **Your changes go live** within 10-15 minutes

---

## 💰 Cost Breakdown

- **Render Web Service:** $25/month
- **PostgreSQL:** $0 (installed on same server)
- **SSL Certificate:** $0 (free from Render)
- **Total:** $25/month 🎉

---

## ✅ Checklist

Before going live, verify:

- [ ] All 10 workers running
- [ ] PostgreSQL connected
- [ ] Database migrated (all 10 tables)
- [ ] Health endpoint returns 200 OK
- [ ] Telegram notifications working
- [ ] Binance API connected
- [ ] OpenAI API working
- [ ] GitHub auto-commit enabled
- [ ] Custom domain configured (if applicable)
- [ ] All secrets properly set

---

## 🆘 Support

If you encounter issues:

1. **Check Render logs** in dashboard
2. **Check Telegram** for system alerts
3. **Verify environment variables** are set correctly
4. **Test health endpoint** to verify service is up
5. **Review migration logs** for database issues

---

## 🎉 Success!

Once everything is running:

✅ **Production deployment complete!**  
✅ **24/7 trading active**  
✅ **Auto-deployment from Replit**  
✅ **Full monitoring with Telegram alerts**  
✅ **Zero extra costs beyond $25/month**

**Happy trading! 🚀**
