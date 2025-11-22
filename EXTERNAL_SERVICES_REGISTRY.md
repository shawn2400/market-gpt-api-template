# 📋 AlgoGPT - External Services & Cost Registry
## Complete API Services with Monthly Budget Breakdown

**Last Updated**: November 22, 2025
**Currency**: USD
**System Philosophy**: Pay per use + Monthly caps for safety

---

## 🤖 AI/LLM PROVIDERS (Primary Expense)

### Tier 1: Primary Decision Makers (Required)

#### 1. **DeepSeek API** ⭐ PRIMARY
- **Role**: CEO - Primary trade decisions, strategy optimization
- **Model**: DeepSeek-V3 (text)
- **Cost**: ~$5.00 per critical trade decision
- **Monthly Budget**: $100.00 (20 critical decisions max)
- **Status**: ✅ ACTIVE
- **API Key**: `DEEPSEEK_API_KEY` (secret)
- **Docs**: https://platform.deepseek.com
- **Backup**: Can operate without it (falls back to Gemini)

#### 2. **Google Gemini API** 🟢 FALLBACK
- **Role**: Data Director - Fallback AI, chart analysis, multi-source fusion
- **Model**: Gemini-2.0 Flash
- **Cost**: ~$2.00 per data confirmation
- **Monthly Budget**: $40.00
- **Status**: ✅ ACTIVE
- **API Key**: `GEMINI_API_KEY` (secret)
- **Docs**: https://ai.google.dev
- **Backup**: Built-in fallback if DeepSeek unavailable

#### 3. **Anthropic Claude API** 🔄 OPTIONAL
- **Role**: Strategic analysis, risk assessment (optional)
- **Model**: Claude-3-Haiku
- **Cost**: ~$4.00 per strategic session
- **Monthly Budget**: $20.00 (unused currently)
- **Status**: ✅ INSTALLED (not actively used)
- **API Key**: `ANTHROPIC_API_KEY` (secret)
- **Docs**: https://console.anthropic.com
- **Usage**: Consensus voting (quantum council)

#### 4. **Alibaba DashScope API** 🟡 OPTIONAL
- **Role**: Asian market analysis (optional)
- **Model**: Qwen-Turbo
- **Cost**: ~$1.50 per Asian market decision
- **Monthly Budget**: $15.00 (unused currently)
- **Status**: ✅ INSTALLED (not actively used)
- **API Key**: `DASHSCOPE_API_KEY` (secret)
- **Docs**: https://dashscope.aliyun.com
- **Usage**: Consensus voting (quantum council)

#### 5. **XAI / Grok API** 🔴 OPTIONAL
- **Role**: Backup AI provider, urgent alerts
- **Model**: Grok-1
- **Cost**: ~$3.00 per execution signal
- **Monthly Budget**: $30.00 (unused currently)
- **Status**: ✅ INSTALLED (not actively used)
- **API Key**: `XAI_API_KEY` (secret)
- **Docs**: https://x.ai
- **Usage**: Consensus voting (quantum council)

#### 6. **OpenAI API** ❌ DEPRECATED
- **Role**: DEPRECATED - Replaced by DeepSeek (95% cheaper)
- **Cost**: $0.00 (not in use)
- **Status**: ❌ DISABLED (historical, backup only)
- **Note**: Kept for emergency fallback only

---

## 💱 TRADING & MARKET DATA

### Binance Futures API
- **Role**: Market data, order execution, account management
- **Cost**: FREE for Futures (no market data API fees for basic endpoints)
- **Status**: ✅ ACTIVE
- **API Keys**: `BINANCE_API_KEY`, `BINANCE_API_SECRET` (secrets)
- **Docs**: https://binance-docs.github.io/apidocs/
- **Rate Limits**: 1200 requests/min shared
- **Features Used**:
  - ✅ Futures account data (free)
  - ✅ Klines/candles (free)
  - ✅ Order execution (free)
  - ✅ Position management (free)

---

## 📱 NOTIFICATION & MONITORING

### Telegram Bot API
- **Role**: User alerts, notifications, interactive callbacks
- **Cost**: FREE (Telegram API is free)
- **Status**: ✅ ACTIVE
- **API Key**: `TELEGRAM_BOT_TOKEN` (secret)
- **Chat ID**: `TELEGRAM_CHAT_ID` (secret)
- **Admin IDs**: `TELEGRAM_ADMIN_IDS` (secret)
- **Docs**: https://core.telegram.org/bots/api
- **Features Used**:
  - ✅ Trade notifications
  - ✅ Daily reports
  - ✅ Interactive approval buttons
  - ✅ HTML formatting
  - ✅ Inline keyboards

---

## 💾 DATA PERSISTENCE & CACHING

### Neon PostgreSQL (Managed by Replit)
- **Role**: Primary database for all position/trade history
- **Cost**: Included in Replit deployment
- **Status**: ✅ ACTIVE
- **Connection**: `DATABASE_URL` (secret)
- **Databases**: 
  - `neondb` (main)
  - Automatic backups
  - Auto-resumption enabled
- **Tables**:
  - Positions (current + historical)
  - Trades (all execution logs)
  - Orders (SL/TP tracking)
  - Risk events (circuit breaker logs)

---

## 🔄 WORKFLOW INTEGRATION

### N8N Webhook Integration
- **Role**: External workflow automation, news ingestion (optional)
- **Cost**: Varies ($0-50/month depending on usage)
- **Status**: ✅ INSTALLED
- **API Key**: `N8N_WEBHOOK_SECRET` (secret)
- **Usage**: External triggers, data ingestion pipelines
- **Note**: Can operate without it (internal trading loop autonomous)

---

## 🔐 INFRASTRUCTURE & SECURITY

### GitHub Repository
- **Role**: Code versioning and deployment
- **Cost**: FREE (GitHub public/private)
- **Status**: ✅ ACTIVE
- **Token**: `GITHUB_TOKEN` (secret)
- **Auto-Deploy**: Yes (Render.com integration)

### Render.com Deployment (Production)
- **Role**: 24/7 live trading environment
- **Cost**: $7-15/month (background workers + compute)
- **Status**: ✅ ACTIVE (Production)
- **Uptime**: 24/7 trading
- **Workers**: 11 background workers
- **Auto-Restart**: Yes

---

## 📊 MONTHLY BUDGET BREAKDOWN

### Recommended Monthly Allocation

| Service | Tier | Monthly Budget | Usage Target | Notes |
|---------|------|---|---|---|
| **DeepSeek API** | Tier 1 | $100.00 | 20 decisions | Primary AI |
| **Gemini API** | Tier 1 | $40.00 | 20 calls | Fallback AI |
| **Claude API** | Tier 3 | $0.00 | 0 calls | Optional consensus |
| **DashScope API** | Tier 3 | $0.00 | 0 calls | Optional consensus |
| **Grok API** | Tier 3 | $0.00 | 0 calls | Optional consensus |
| **Binance API** | Core | FREE | Unlimited | Trading only |
| **Telegram API** | Core | FREE | Unlimited | Notifications |
| **N8N Webhook** | Optional | $20.00 | 100 calls | External integration |
| **Neon Database** | Core | Included | Unlimited | Replit included |
| **GitHub** | Core | FREE | Unlimited | Versioning |
| **Render.com** | Production | $10.00 | 24/7 | Live trading |
| **Redis Cloud** | Optional | $0.00 | 1GB free | Session caching |
| | | | |
| **TOTAL MONTHLY** | | **~$170.00** | | **Cost with active AI** |
| **MINIMUM MONTHLY** | | **$10.00** | | **Render.com only** |

---

## ⚙️ CONFIGURATION STATUS

### Currently Active Services
✅ **Must Have** (trading won't work without):
- Binance Futures API
- Telegram Bot (for alerts)
- PostgreSQL (data persistence)
- Neon Database (connected)

✅ **Highly Recommended** (for AI trading):
- DeepSeek API (primary AI decisions)
- Gemini API (fallback)

🟡 **Optional** (enhanced features):
- Anthropic Claude (consensus voting)
- DashScope (Asian markets)
- Grok (backup AI)
- N8N (external workflows)

❌ **Deprecated**:
- OpenAI API (replaced by DeepSeek, kept for emergency only)

---

## 💰 COST OPTIMIZATION TIPS

### To Minimize Monthly Costs:
1. **Use DeepSeek as primary** - Save 95% vs OpenAI
2. **Gemini fallback only** - Don't call both every trade
3. **Consensus voting optional** - Disable Claude/DashScope/Grok if budget tight
4. **Batch API calls** - Group multiple queries per API request
5. **Cache results** - Redis stores recent analyses (free tier)

### Budget Control Mechanisms:
- ✅ **BUDGET_LIMIT_MONTHLY**: Set max monthly spend in env var
- ✅ **SMART_BUDGET_ALLOCATION**: Tokens redistributed monthly
- ✅ **COST_BENEFIT_ANALYSIS**: Only high-confidence trades use tokens
- ✅ **FALLBACK CHAINS**: If quota exceeded → use fallback AI
- ✅ **CIRCUIT BREAKER**: System pauses if budget 100% used

---

## 🔗 QUICK REFERENCE - API KEYS NEEDED

| Key | Service | Required | Status |
|-----|---------|----------|--------|
| `BINANCE_API_KEY` | Binance | ✅ YES | ✅ Active |
| `BINANCE_API_SECRET` | Binance | ✅ YES | ✅ Active |
| `DEEPSEEK_API_KEY` | DeepSeek | ✅ YES | ✅ Active |
| `GEMINI_API_KEY` | Google Gemini | ⭐ Recommended | ✅ Active |
| `TELEGRAM_BOT_TOKEN` | Telegram | ✅ YES | ✅ Active |
| `TELEGRAM_CHAT_ID` | Telegram | ✅ YES | ✅ Active |
| `TELEGRAM_ADMIN_IDS` | Telegram | ✅ YES | ✅ Active |
| `DATABASE_URL` | Neon PostgreSQL | ✅ YES | ✅ Active |
| `ANTHROPIC_API_KEY` | Claude | 🟡 Optional | ✅ Installed |
| `DASHSCOPE_API_KEY` | Alibaba | 🟡 Optional | ✅ Installed |
| `XAI_API_KEY` | Grok | 🟡 Optional | ✅ Installed |
| `OPENAI_API_KEY` | OpenAI | ❌ NO | ❌ Disabled |
| `N8N_WEBHOOK_SECRET` | N8N | 🟡 Optional | ✅ Installed |
| `GITHUB_TOKEN` | GitHub | ✅ YES | ✅ Active |
| `NEON_API_KEY` | Neon | 🟡 Optional | ✅ Active |
| `NEON_PROJECT_ID` | Neon | ✅ YES | ✅ Active |
| `NEON_ENDPOINT_ID` | Neon | ✅ YES | ✅ Active |

---

## 🚀 MONTHLY OPERATIONS CHECKLIST

- [ ] Monitor DeepSeek API usage in logs
- [ ] Check monthly invoice from DeepSeek
- [ ] Verify Render.com billing monthly
- [ ] Test Telegram bot connectivity weekly
- [ ] Review position history in PostgreSQL
- [ ] Validate API key rotation if needed
- [ ] Update budget allocation if account size changes
- [ ] Archive old position data quarterly

---

## 📞 SUPPORT & DOCUMENTATION

- **DeepSeek**: https://api-docs.deepseek.com
- **Gemini**: https://ai.google.dev/docs
- **Binance**: https://binance-docs.github.io/apidocs/
- **Telegram**: https://core.telegram.org/bots
- **Neon**: https://neon.tech/docs
- **Render**: https://render.com/docs

---

**Version**: 1.0  
**Last Review**: Nov 22, 2025  
**Next Review**: Dec 22, 2025
