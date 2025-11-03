# 🚀 AlgoGPT — Multi-AI Autonomous Trading Platform

```
    ╔═══════════════════════════════════════════════════════════════╗
    ║   █████╗ ██╗      ██████╗  ██████╗  ██████╗ ██████╗ ████████╗ ║
    ║  ██╔══██╗██║     ██╔════╝ ██╔═══██╗██╔════╝ ██╔══██╗╚══██╔══╝ ║
    ║  ███████║██║     ██║  ███╗██║   ██║██║  ███╗██████╔╝   ██║    ║
    ║  ██╔══██║██║     ██║   ██║██║   ██║██║   ██║██╔═══╝    ██║    ║
    ║  ██║  ██║███████╗╚██████╔╝╚██████╔╝╚██████╔╝██║        ██║    ║
    ║  ╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝  ╚═════╝ ╚═╝        ╚═╝    ║
    ║                                                                 ║
    ║        🤖 Autonomous AI-Powered Futures Trading Engine         ║
    ╚═══════════════════════════════════════════════════════════════╝
```

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![GPT-5](https://img.shields.io/badge/GPT--5-2025--08--07-412991?style=for-the-badge&logo=openai&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Neon-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![License](https://img.shields.io/badge/License-Private-red?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Live%2024/7-success?style=for-the-badge)

**Version:** `3.6.0` | **Uptime:** 99.9% | **Deployment:** Replit + Render

[🎯 Features](#-features) • [📦 Installation](#-installation--setup) • [⚙️ Configuration](#️-configuration) • [📊 Performance](#-performance-metrics) • [🗺️ Roadmap](#️-roadmap)

</div>

---

## 🌟 Overview | סקירה כללית

**AlgoGPT** היא פלטפורמת מסחר אלגוריתמי אוטונומית המבוססת על בינה מלאכותית מתקדמת. המערכת פועלת 24/7 על Binance Futures ומנתחת באופן רציף 531 שווקים שונים, מזהה הזדמנויות מסחר איכותיות, ומבצעת עסקאות באופן אוטומטי עם ניהול סיכונים דינמי.

**AlgoGPT** is a cutting-edge autonomous algorithmic trading platform powered by multi-AI consensus. It operates 24/7 on Binance Futures, continuously analyzing 531 markets, identifying high-quality trading opportunities, and executing trades automatically with dynamic risk management.

### 🎯 Core Capabilities | יכולות ליבה

- ⚡ **24/7 Automated Trading** — מסחר אוטומטי מלא עם ביצוע מיידי ואישורים בטלגרם
- 🧠 **Multi-AI Decision Engine** — קונצנזוס של 3 מודלי AI: GPT-5, DeepSeek, Grok
- 📊 **Market Intelligence** — ניתוח רב-מסגרות זמן (4H/1H/15M) עם משקולות דינמיות
- 🛡️ **Advanced Risk Management** — SL/TP דינמיים, ATR trailing, BE logic, ניהול אוטומטי
- 🔄 **Auto-Flip & Adaptation** — התאמה אוטומטית למצבי שוק משתנים
- 📈 **GRID Trading** — מסחר רשת אוטומטי לשווקים צידיים
- 🎯 **Target Performance** — 4-10 עסקאות איכותיות ביום, RR ≥ 1.3:1

---

## 🏗️ System Architecture | ארכיטקטורה

```
┌─────────────────────────────────────────────────────────────────────┐
│              AlgoGPT - Multi-AI Autonomous Trading Platform          │
│                        24/7 Live Production System                   │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                ┌──────────────────┼──────────────────┐
                │                  │                  │
        ┌───────▼────────┐ ┌──────▼───────┐ ┌───────▼────────┐
        │  🧠 AI Layer   │ │ 📊 Scanner   │ │ 🎯 Execution   │
        │  Multi-Model   │ │  531 Markets │ │  Binance API   │
        │   Consensus    │ │   3 TFs      │ │  Futures Only  │
        └───────┬────────┘ └──────┬───────┘ └───────┬────────┘
                │                  │                  │
                └──────────────────┼──────────────────┘
                                   │
                ┌──────────────────┼──────────────────┐
                │                  │                  │
        ┌───────▼────────┐ ┌──────▼───────┐ ┌───────▼────────┐
        │ 🛡️ Risk Mgmt  │ │ 🔄 N8N Auto  │ │ 📱 Telegram    │
        │  Dynamic SL/TP │ │  Workflows   │ │  Interactive   │
        │  ATR Trailing  │ │  News/Alerts │ │  Approvals     │
        └───────┬────────┘ └──────┬───────┘ └───────┬────────┘
                │                  │                  │
                └──────────────────┼──────────────────┘
                                   │
                        ┌──────────▼──────────┐
                        │  💾 PostgreSQL DB   │
                        │   Data Persistence  │
                        │   Audit & Learning  │
                        └─────────────────────┘

    Core Workers:                        Monitoring:
    ├─ GPT-5 Orchestrator (30min)       ├─ System Heartbeat (10min)
    ├─ Auto Scanner (60sec)              ├─ Position Monitor (30min)
    ├─ Position Monitor (30min)          ├─ Sentinel Security (5min)
    ├─ Daily Digest (8:00/22:00)         └─ Daily Health Report
    ├─ N8N Bridge (continuous)
    └─ GitHub Auto-Commit (60min)
```

---

## ✨ Features

### 🤖 AI & Intelligence

- **GPT-5 Primary Engine** — OpenAI's `gpt-5-2025-08-07` model for advanced market analysis
- **Multi-AI Consensus** — 3-provider voting system (GPT-5 + DeepSeek + Grok) for enhanced accuracy
- **Adaptive Prompts** — Self-adjusting instructions based on market regime (trending/choppy/volatile)
- **Weighted Multi-Timeframe** — 4H (50%) + 1H (30%) + 15M (20%) balanced analysis
- **Market Intelligence** — Automatic regime detection, mood scoring, volatility classification
- **Portfolio Intelligence** — Exposure management, correlation prevention, position limits

### 📈 Trading Capabilities

- **24/7 Automated Execution** — Continuous market monitoring and trade execution
- **Binance Futures API** — Direct integration with futures markets (USDT-margined)
- **GRID Trading** — Automated grid strategies for sideways/choppy markets
- **Dynamic Position Sizing** — Equity-based allocation (2-10x leverage) based on:
  - Trade quality score (0-10)
  - AI confidence level
  - Risk/Reward ratio
  - Market volatility (ATR)
- **Multiple Execution Modes:**
  - `MARKET` — Immediate execution
  - `HYBRID` — Limit orders with stop-loss escalation
  - `AUTO` — Smart mode selection
- **Auto-Flip Logic** — Dynamic position reversal on trend changes with multi-system validation

### 🛡️ Risk Management

- **ATR-Based Trailing Stops** — Dynamic stop-loss adjustment with:
  - Freeze logic during low volatility
  - Spike detection and protection
  - Regime-aware multipliers
- **Multi-Level TP Ladders** — Automatic profit-taking at multiple levels
- **Break-Even Logic** — Smart BE activation with offset/guard
- **Daily Loss Circuit Breaker** — Automatic trading halt on excessive losses
- **Position Correlation Prevention** — Avoids correlated positions
- **Liquidity Filters** — Ensures sufficient market depth
- **Quality Scoring** — 0-10 score based on multi-TF confluence
- **Daily Trade Caps** — Maximum trades per day limit
- **Cooldown Periods** — Symbol-level cooldowns after trades
- **Deduplication** — Prevents duplicate trade proposals

### 🔧 Infrastructure & Automation

- **FastAPI Backend** — High-performance async API server
- **Gunicorn WSGI Server** — Production-grade serving with multi-workers
- **PostgreSQL Database** — Complete data persistence (Neon-hosted)
- **N8N Workflow Automation** — External integrations (news, alerts, workflows)
- **Telegram Bot Integration:**
  - Rich HTML notifications with emojis
  - Interactive approval buttons
  - Real-time position updates
  - Daily digest reports (8:00/22:00 Israel Time)
- **Security & Auth:**
  - Bearer token authentication
  - HMAC signature verification
  - Anti-replay protection (Redis)
  - Idempotency keys
- **Monitoring & Health:**
  - System heartbeat checks (10min)
  - Position monitoring (30min)
  - Sentinel security scans (5min)
  - Prometheus metrics
  - Health endpoints (`/health`, `/readyz`)
- **GitHub Auto-Commit** — Automatic code versioning every 60 minutes

---

## 📦 Installation & Setup

### Prerequisites

```bash
# Required
- Python 3.11+
- PostgreSQL database (Replit provides Neon)
- Binance Futures API keys (with futures trading enabled)
- OpenAI API key (GPT-5 access required)
- Telegram Bot token & Chat ID

# Optional
- DeepSeek API key (for multi-AI consensus)
- xAI/Grok API key (for multi-AI consensus)
- N8N instance (for workflow automation)
```

### Quick Start (Replit)

```bash
# 1. Fork/Clone this repository to Replit

# 2. Configure Secrets (use Replit Secrets UI)
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_secret
OPENAI_API_KEY=sk-proj-...
TELEGRAM_BOT_TOKEN=7197767713:AAFxnox7IyaIU35VuGNyt_TFLPKEdKs47jE
TELEGRAM_CHAT_ID=your_chat_id
DATABASE_URL=postgresql://...  # Auto-created by Replit

# Optional
DEEPSEEK_API_KEY=sk-...
XAI_API_KEY=xai-...
N8N_WEBHOOK_URL=https://...

# 3. Start Workflows
# All workflows are pre-configured and will start automatically
# Main workflows:
# - AlgoGPT Server (FastAPI on port 5000)
# - Auto Scanner (60sec cycles)
# - GPT-5 Central Brain (30min orchestration)
# - Position Monitor (30min checks)
# - Daily Digest (morning/evening reports)
# - GitHub Auto-Commit (60min backups)

# 4. Verify Health
curl https://your-repl-url.repl.co/health

# 5. Approve Trades via Telegram
# Proposals will be sent to your Telegram with approval buttons
# Click ✅ Approve or ❌ Reject
```

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `BINANCE_API_KEY` | Binance Futures API key | - | ✅ Yes |
| `BINANCE_API_SECRET` | Binance Futures secret | - | ✅ Yes |
| `OPENAI_API_KEY` | OpenAI API key (GPT-5) | - | ✅ Yes |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | - | ✅ Yes |
| `TELEGRAM_CHAT_ID` | Telegram chat ID | - | ✅ Yes |
| `DATABASE_URL` | PostgreSQL connection | - | ✅ Yes |
| `DEEPSEEK_API_KEY` | DeepSeek API key | - | ⚪ Optional |
| `XAI_API_KEY` | xAI/Grok API key | - | ⚪ Optional |
| `AUTO_RUN` | Enable auto-execution | `1` | ⚪ Optional |
| `EXECUTE_TRADES` | Execute live trades | `1` | ⚪ Optional |
| `REQUIRE_TELEGRAM_APPROVAL` | Require approval | `1` | ⚪ Optional |
| `APPROVAL_ENABLED` | Enable approval workflow | `1` | ⚪ Optional |
| `TRAIL_ENABLE` | Enable ATR trailing | `1` | ⚪ Optional |
| `BE_GUARD_ENABLE` | Enable BE logic | `1` | ⚪ Optional |

---

## ⚙️ Configuration

### Workflow Configurations

All workers are configured as Replit workflows and run automatically:

```yaml
AlgoGPT Server:
  command: gunicorn -c gunicorn_conf.py main:app
  port: 5000
  output: webview

Auto Scanner:
  command: python workers/gpt_auto_suggest.py
  interval: 60 seconds
  output: console

GPT-5 Central Brain:
  command: python workers/gpt5_orchestrator.py
  interval: 30 minutes
  output: console

Position Monitor:
  command: python workers/position_monitor.py
  interval: 30 minutes
  output: console

Daily Digest:
  command: python workers/daily_digest.py
  schedule: 8:00, 22:00 Israel Time
  output: console

GitHub Auto-Commit:
  command: python workers/github_auto_commit.py
  interval: 60 minutes
  output: console
```

### Policy Files

Risk and trade policies are managed via YAML:

- `policies/dynamic_policy.yaml` — Trail/BE/Ladder/Thresholds/Sizing/Regime
- `policies/ops_policy.yaml` — Master switches, profiles, schedules, quality gates

### API Endpoints

**Health & Monitoring:**
```
GET  /health                    # Basic health check
GET  /readyz                    # Ready check
GET  /api/health                # API health status
GET  /ultra/health              # Ultra health check
GET  /ultra/metrics             # Prometheus metrics (Bearer auth)
```

**Trading & Positions:**
```
POST /trade/open                # Open new position (Bearer auth)
POST /trade/close               # Close position (Bearer auth)
POST /manage-once               # Manual position management
GET  /positions                 # View open positions
```

**Operations & Approvals:**
```
POST /ops/ticket                # Create approval ticket
GET  /ops/ui                    # Approval UI
POST /ops/approve               # Approve trade (Bearer auth)
POST /ops/approve/signed        # Approve with HMAC signature
```

**Scanning & Analysis:**
```
GET  /scan/public-now           # Current market scan
GET  /scan/public-topk          # Top opportunities
GET  /topk                      # Top K candidates (JSON)
GET  /topk.csv                  # Top K candidates (CSV)
```

### Telegram Commands

Interact with the bot via Telegram:

- `/status` — System status & open positions
- `/approve <ticket_id>` — Approve pending trade
- `/reject <ticket_id>` — Reject pending trade
- `/positions` — View open positions
- `/pnl` — Today's P&L summary
- `/health` — System health check

---

## 🛠️ Tech Stack

### Backend
- **FastAPI** — Modern async web framework
- **Gunicorn** — Production WSGI server
- **Python 3.11** — Core language

### AI & Machine Learning
- **OpenAI GPT-5** — Primary decision engine (gpt-5-2025-08-07)
- **DeepSeek R1** — Alternative AI provider
- **xAI Grok** — Third AI provider for consensus

### Database & Storage
- **PostgreSQL (Neon)** — Primary database
- **SQLAlchemy** — ORM
- **Psycopg2** — PostgreSQL adapter

### Exchange Integration
- **Binance Futures API** — Trading execution
- **python-binance** — SDK
- **httpx** — Async HTTP client

### Automation & Integration
- **N8N** — Workflow automation
- **Telegram Bot API** — Notifications & approvals

### Monitoring & Security
- **Prometheus** — Metrics collection
- **Grafana** — Dashboards
- **HMAC Signatures** — Request authentication
- **Redis** — Anti-replay protection
- **psutil** — System monitoring

---

## 📁 File Structure

```
AlgoGPT/
├── main.py                      # FastAPI server entry point
├── gunicorn_conf.py             # Gunicorn configuration
├── requirements.txt             # Python dependencies
├── runtime.txt                  # Python version (3.11)
│
├── routes/                      # API endpoints
│   ├── health.py                # Health checks
│   ├── n8n.py                   # N8N integration
│   ├── trade.py                 # Trade execution
│   ├── ops_approval.py          # Approval workflow
│   ├── position_ops.py          # Position management
│   ├── scan.py                  # Market scanning
│   └── ...
│
├── workers/                     # Background workers
│   ├── gpt_auto_suggest.py      # AI trade scanner (60sec)
│   ├── gpt5_orchestrator.py     # Central brain (30min)
│   ├── position_monitor.py      # Position tracking (30min)
│   ├── daily_digest.py          # Daily reports (8:00/22:00)
│   ├── system_heartbeat.py      # Health monitoring (10min)
│   ├── sentinel_security.py     # Security scans (5min)
│   ├── n8n_bridge.py            # N8N bridge (continuous)
│   ├── github_auto_commit.py    # Auto-commit (60min)
│   └── ...
│
├── utils/                       # Core utilities
│   ├── ai_trade_scorer.py       # Multi-AI consensus scoring
│   ├── multi_tf_manager.py      # Multi-timeframe analysis
│   ├── dynamic_sltp_manager.py  # Dynamic SL/TP management
│   ├── auto_flip.py             # Auto-flip logic
│   ├── market_intelligence.py   # Regime detection
│   ├── adaptive_prompts.py      # AI prompt optimization
│   ├── binance_client.py        # Binance API client
│   ├── telegram_notifier.py     # Telegram notifications
│   ├── grid_planner.py          # GRID trade planning
│   └── ...
│
├── policies/                    # Risk & trade policies (YAML)
│   ├── dynamic_policy.yaml      # Dynamic management rules
│   └── ops_policy.yaml          # Operational policies
│
├── config/                      # Configuration files
│   ├── symbols_allowlist.json   # Allowed symbols
│   ├── scan_rules.json          # Scanning rules
│   └── ...
│
├── scripts/                     # Utility scripts
│   ├── smoke.sh                 # Smoke tests
│   ├── approve_via_telegram.sh  # CLI approval
│   └── ...
│
├── tests/                       # Unit tests
│   ├── test_binance.py
│   ├── test_health.py
│   └── ...
│
└── docs/                        # Documentation
    ├── DEPLOYMENT.md
    ├── N8N_WORKFLOWS.md
    └── ...
```

---

## 📊 Performance Metrics

### Target Performance
- **Daily Trades:** 4-10 high-quality setups
- **Risk/Reward:** Minimum 1.3:1 (enforced)
- **Multi-AI Confidence:** >70% required for execution
- **System Uptime:** 99.9% (24/7 operation)
- **Max Leverage:** 2-10x (dynamic based on quality)

### Quality Requirements
- Multi-timeframe alignment (4H/1H/15M)
- Technical confluence (RSI, MACD, EMA, ADX, Volume)
- BTC anchor correlation check
- Liquidity validation
- AI consensus (3 providers)

### Risk Controls
- Daily loss circuit breaker
- Maximum 4 concurrent positions
- Position correlation prevention
- Symbol-level cooldowns
- Quality score threshold (≥6/10)

---

## 🗺️ Roadmap

See [ROADMAP.md](docs/ROADMAP.md) for detailed scaling plan.

### Phase 1: Core Stability ✅
- [x] Multi-AI consensus integration
- [x] ATR trailing with freeze logic
- [x] Auto-flip on reversals
- [x] GRID trading support
- [x] PostgreSQL persistence
- [x] Telegram interactive approvals

### Phase 2: Intelligence Enhancement 🔄
- [x] GPT-5 orchestrator
- [x] Market regime detection
- [x] Adaptive AI prompts
- [x] Portfolio intelligence
- [ ] Self-learning from trade history
- [ ] Advanced backtesting engine

### Phase 3: Scaling & Optimization 📋
- [ ] Multi-exchange support (Bybit, OKX)
- [ ] Advanced portfolio optimization
- [ ] ML-based position sizing
- [ ] Real-time sentiment analysis
- [ ] Advanced correlation matrices
- [ ] Multi-account management

### Phase 4: Enterprise Features 📋
- [ ] White-label deployment
- [ ] Multi-user support
- [ ] Advanced analytics dashboard
- [ ] Custom strategy builder
- [ ] API for third-party integrations

---

## 🤝 Contributing & License

### License
This project is **private and proprietary**. All rights reserved.

### Contributing
This is a private trading system. Contributions are not accepted from external parties.

---

## 📞 Contact & Support

### Telegram
- **Bot:** [@algogpt_bot](https://t.me/algogpt_bot)
- **Support:** Contact via Telegram for issues

### GitHub
- **Issues:** Use GitHub Issues for bug reports
- **Discussions:** GitHub Discussions for questions

---

## ⚠️ Disclaimer

**Trading Risk Warning:**  
Cryptocurrency futures trading involves substantial risk of loss and is not suitable for every investor. Past performance is not indicative of future results. This software is provided "as is" without any warranties. Use at your own risk.

**No Financial Advice:**  
This software is for educational and informational purposes only. It does not constitute financial, investment, or trading advice. Always consult with qualified financial professionals before making trading decisions.

---

<div align="center">

**Built with ❤️ using FastAPI, GPT-5, and Python**

*AlgoGPT — Autonomous AI-Powered Futures Trading* 🚀

</div>
