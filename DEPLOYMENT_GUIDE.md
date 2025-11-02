# AlgoGPT Phase 3.7 - Deployment Guide to Render.com

## 🎯 Status: Ready for Production Deployment

### ✅ Pre-Deployment Checklist Complete

- ✅ **Public Observability Infrastructure** - 12 endpoints ready
- ✅ **All 6 Workflows Running** - Scanner, Server, Monitors all operational
- ✅ **GitHub Synchronized** - 20/20 files synced
- ✅ **Version Updated** - 3.7.0 (Public Observability Phase)
- ✅ **Security Hardened** - HMAC signatures, sanitized logs, no secrets exposed
- ✅ **Trade Flow Operational** - Scanner → ingest → Telegram → execution
- ✅ **render.yaml Updated** - All public endpoints whitelisted

---

## 📋 Deployment Steps

### Option 1: Manual Deploy via Render Dashboard (Recommended)

1. **Go to Render Dashboard**
   ```
   https://dashboard.render.com
   ```

2. **Select the Service**
   - Find and click on: **algogpt-prod**
   
3. **Trigger Manual Deploy**
   - Click **"Manual Deploy"** button (top right)
   - Select **"Deploy latest commit"**
   - Confirm deployment

4. **Monitor Deployment**
   - Watch the build logs
   - Wait for status: **Live** (typically 5-10 minutes)

5. **Verify Public Endpoints**
   ```bash
   # Test all public endpoints
   curl https://algogpt-prod.onrender.com/status/public
   curl https://algogpt-prod.onrender.com/mesh/public
   curl https://algogpt-prod.onrender.com/dashboard
   ```

---

### Option 2: Create New Service from Scratch

1. **Connect Repository**
   ```
   https://dashboard.render.com/select-repo
   ```

2. **Select Repository**
   - Choose: **shawn2400/algogpt**
   - Branch: **main**

3. **Configure Service**
   - **Blueprint**: Select `render.yaml`
   - Click **"Apply"**

4. **Add Required Secrets**
   Navigate to **Environment** tab and add:
   ```
   BINANCE_API_KEY=<your_key>
   BINANCE_API_SECRET=<your_secret>
   OPENAI_API_KEY=<your_key>
   TELEGRAM_BOT_TOKEN=<your_token>
   TELEGRAM_CHAT_ID=449087907
   TELEGRAM_ADMIN_IDS=449087907
   OPS_SIGN_SECRET=<generate_random_64_chars>
   AI_MESH_SECRET=<generate_random_64_chars>
   REDIS_URL=<your_redis_url>
   ```

5. **Deploy**
   - Click **"Create Web Service"**
   - Wait for deployment to complete

---

## 🔗 Post-Deployment URLs

Once deployed, your production system will be available at:

### Public Observability Endpoints
```
STATUS:     https://algogpt-prod.onrender.com/status/public
MESH:       https://algogpt-prod.onrender.com/mesh/public
MESH_PEERS: https://algogpt-prod.onrender.com/mesh/peers
GIT:        https://algogpt-prod.onrender.com/git/public
RENDER:     https://algogpt-prod.onrender.com/render/public
TRADES:     https://algogpt-prod.onrender.com/trades/public
PNL:        https://algogpt-prod.onrender.com/pnl/public
LOGS:       https://algogpt-prod.onrender.com/logs/tail/public?name=main&lines=200
DASHBOARD:  https://algogpt-prod.onrender.com/dashboard
```

### Protected Endpoints (Require Auth)
```
DOCS:       https://algogpt-prod.onrender.com/docs
HEALTH:     https://algogpt-prod.onrender.com/health
READYZ:     https://algogpt-prod.onrender.com/readyz
VERSION:    https://algogpt-prod.onrender.com/version
```

---

## 🔐 Security Configuration

### Public Endpoints (No Auth Required)
All public observability endpoints are configured in `SECURITY_PUBLIC_PATHS`:
- `/status/public`
- `/mesh/public`
- `/mesh/peers`
- `/mesh/register` (HMAC-signed only)
- `/git/public`
- `/render/public`
- `/trades/public`
- `/pnl/public`
- `/logs/tail/public`
- `/dashboard`

### Protected Endpoints (Bearer Token Required)
- `/admin/*`
- `/ops/*` (except signed URLs)
- `/webhook/*`
- `/manage-once/*`

### Secrets Sanitization
All public endpoints automatically sanitize:
- API keys
- Tokens
- Secrets
- Passwords
- Bearer tokens

---

## 🎯 Features Available After Deployment

### Phase 3.7 - Public Observability
- ✅ Real-time system status monitoring
- ✅ Mesh network topology visualization
- ✅ GitHub sync status tracking
- ✅ Live trade history feed
- ✅ PnL summary dashboard
- ✅ Sanitized log viewer
- ✅ Auto-refreshing web dashboard (15s interval)

### Phase 3.4 - AI Mesh
- ✅ Multi-agent orchestration (GPT-4o, DeepSeek, AI-X)
- ✅ Weighted consensus voting (40% GPT-4o, 30% DeepSeek, 30% AI-X)
- ✅ Circuit breaker on failures
- ✅ HMAC-secured mesh registration
- ✅ Automatic GitHub synchronization

### Core Trading System
- ✅ 24/7 automated market scanning (531 symbols)
- ✅ AI-powered trade proposals via Telegram
- ✅ GRID trading for sideways markets
- ✅ Dynamic position management (TP/SL/BE/Trailing)
- ✅ News sentiment analysis
- ✅ Fear & Greed Index integration
- ✅ Auto Risk Manager (dynamic leverage/sizing)

---

## 📊 Monitoring & Health Checks

### Health Check Endpoints
```bash
# Kubernetes-style health checks
curl https://algogpt-prod.onrender.com/readyz

# Application health
curl https://algogpt-prod.onrender.com/health

# Version info
curl https://algogpt-prod.onrender.com/version
```

### Logs Access
```bash
# View recent logs (sanitized)
curl "https://algogpt-prod.onrender.com/logs/tail/public?name=main&lines=200"

# Or via dashboard
open https://algogpt-prod.onrender.com/dashboard
```

---

## 🚨 Troubleshooting

### Deployment Failed
1. Check Render build logs
2. Verify all secrets are set correctly
3. Ensure Docker base image is accessible
4. Check `render.yaml` syntax

### Service Not Responding
1. Check health endpoint: `/readyz`
2. Review application logs in Render dashboard
3. Verify Redis connection (if enabled)
4. Check worker processes status

### Public Endpoints Return 404
1. Verify `SECURITY_PUBLIC_PATHS` in render.yaml
2. Check if service restarted after config change
3. Ensure routes are registered in main.py

---

## 📝 Configuration Notes

### Environment Variables
- **Production mode**: `MODE=hybrid`
- **Auto-run enabled**: `AUTO_RUN=1`
- **Trade execution**: `EXECUTE_TRADES=1`
- **Telegram approval**: `REQUIRE_TELEGRAM_APPROVAL=1`
- **Version**: `APP_VERSION=3.7.0`

### Resource Allocation
- **Plan**: Standard ($25/month)
- **Region**: Frankfurt (EU)
- **Workers**: 1 (WEB_CONCURRENCY=1)
- **Disk**: 1GB persistent storage
- **Timeout**: 180s per request

---

## 🎉 Success Indicators

After deployment, verify:
1. ✅ Service status shows **Live**
2. ✅ Health check returns `200 OK`
3. ✅ `/status/public` returns valid JSON
4. ✅ `/dashboard` displays live data
5. ✅ Telegram bot sends startup notification (if enabled)
6. ✅ Scanner workflow starts automatically
7. ✅ Trade proposals appear in Telegram

---

## 📞 Support & Resources

- **GitHub Repo**: https://github.com/shawn2400/algogpt
- **Render Docs**: https://render.com/docs
- **Render Dashboard**: https://dashboard.render.com
- **Documentation**: See `replit.md` for full system architecture

---

**Deployed By**: Replit Agent  
**Deployment Date**: November 2, 2025  
**Version**: 3.7.0 - Public Observability Phase  
**Status**: ✅ Ready for Production
