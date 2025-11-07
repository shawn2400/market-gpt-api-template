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

**Version:** `9.0.0` | **AI Brains:** 5 | **Workers:** 8 | **Strategies:** 7 | **Markets:** 534

[🎯 Features](#-features) • [🧠 AI Brains](#-ai-brains-multi-model-consensus) • [⚙️ Workers](#️-workers-background-processes) • [📊 Strategies](#-trading-strategies) • [🔐 Security](#-security-hmac-signature)

</div>

---

## 🌟 Overview | סקירה כללית

**AlgoGPT v9.0** היא פלטפורמת מסחר אלגוריתמי אוטונומית המבוססת על 5 מודלי AI מתקדמים שפועלים במערך קונצנזוס היררכי. המערכת פועלת 24/7 על Binance Futures, מנתחת באופן רציף 534 שווקים שונים, ומבצעת 4-10 עסקאות איכותיות ביום עם ניהול סיכונים דינמי ומותאם משטר.

**AlgoGPT v9.0** is a cutting-edge autonomous algorithmic trading platform powered by **5 AI brains** operating in hierarchical consensus. It runs 24/7 on Binance Futures, continuously analyzing 534 markets across multiple timeframes, and executes 4-10 high-quality trades daily with regime-adaptive dynamic risk management.

### 🎯 Core Capabilities | יכולות ליבה

- ⚡ **24/7 Automated Trading** — מסחר אוטומטי מלא עם ביצוע מיידי (LIMIT + MARKET)
- 🧠 **5-Brain AI Consensus** — קונצנזוס של 5 מודלי AI (GPT-5, Gemini 2 Pro, DeepSeek, Grok, Claude)
- 📊 **534 Markets Scanning** — סריקה רצופה של כל שווקי Binance Futures
- 🛡️ **Regime-Based Risk Management** — 4 משטרי שוק (TRENDING/CHOPPY/VOLATILE/SIDEWAYS)
- 🔄 **7 Trading Strategies** — Mean-Reversion, Scalping, Range-Bounce, Trend-Following, Breakout, GRID, SPOT
- 📈 **12 Technical Indicators** — RSI, EMA, ATR, ADX, MACD, Bollinger, VWAP, Keltner, OBV, QQE, SMC, Volume
- 🎯 **Target Performance** — 4-10 עסקאות ביום, Win Rate ≥47%, RR ≥1.3:1
- 🔐 **HMAC Signature Security** — חתימה דינמית לכל בקשה + anti-replay protection

---

## 🧠 AI Brains (Multi-Model Consensus)

AlgoGPT משתמשת ב**5 AI Brains** שפועלים במערך קונצנזוס היררכי. כל brain מצביע APPROVE/REJECT על כל הצעת מסחר, ונדרשים **≥3 APPROVE** מתוך 5 כדי לבצע trade.

### 🤖 AI Brain #1: GPT-5 (OpenAI)
- **Model**: `gpt-5-2025-08-07`
- **Role**: Lead Orchestrator - מנתח שוק מתקדם
- **Temperature**: 0.7
- **Max Tokens**: 300
- **Status**: ✅ Active

### 🌟 AI Brain #2: Gemini 2 Pro (Google)
- **Model**: `gemini-2.0-flash-exp`
- **Role**: Fast Multi-Modal Analyst - ניתוח רב-מודלי מהיר
- **Temperature**: 0.7
- **Max Tokens**: 300
- **Status**: ⚠️ Quota Limited (50/day free tier)

### 🧠 AI Brain #3: DeepSeek
- **Model**: `deepseek-chat`
- **Role**: Deep Pattern Analyst - ניתוח דפוסים עמוק
- **Temperature**: 0.7
- **Max Tokens**: 300
- **Status**: ✅ Active

### ⚡ AI Brain #4: Grok (XAI)
- **Model**: `grok-2-latest`
- **Role**: Contrarian Analyst - ניתוח קונטרריאני
- **Temperature**: 0.8
- **Max Tokens**: 300
- **Status**: ✅ Active

### 🛡️ AI Brain #5: Claude Sonnet 3.5 (Anthropic)
- **Model**: `claude-3-5-sonnet-20241022`
- **Role**: Conservative Risk Validator - ולידציית סיכונים שמרנית
- **Temperature**: 0.5
- **Max Tokens**: 300
- **Status**: ✅ Active

### 🗳️ Consensus Mechanism

```python
# Voting Flow:
1. Scout generates trade proposal (MI + SO scores)
2. All 5 AI brains analyze proposal independently
3. Each brain votes APPROVE/REJECT with score (0-10)
4. Consensus decision:
   - ≥3 APPROVE → ✅ Execute Trade
   - <3 APPROVE → ❌ Reject Proposal
5. Final score = median(all_brain_scores)
```

**Example Consensus:**
```
GPT-5:          APPROVE (7.8/10)
Gemini 2 Pro:   APPROVE (7.2/10)
DeepSeek:       REJECT  (5.4/10)
Grok:           APPROVE (8.1/10)
Claude:         REJECT  (6.0/10)

Result: 3/5 APPROVE (60%) → ✅ EXECUTE
Final Score: 7.0/10 (median)
```

---

## ⚙️ Workers (Background Processes)

AlgoGPT מריצה **8 workers** בפרלל, כל אחד אחראי על תפקיד ספציפי במערכת.

### 🌐 Worker #1: AlgoGPT Server
- **File**: `main.py`
- **Command**: `gunicorn -c gunicorn_conf.py main:app`
- **Port**: 5000 (webview)
- **Description**: FastAPI server ראשי - מטפל ב-API requests, webhooks, ו-UI dashboard
- **Environment Variables**:
  - `PORT=5000`
  - `EXECUTE_TRADES=1`
  - `APPROVAL_ENABLED=0` (auto-execute)
  - `ENABLE_MULTI_AI_CONSENSUS=1`

### 🏥 Worker #2: Auto Health Monitor
- **File**: `workers/auto_health_monitor.py`
- **Command**: `python workers/auto_health_monitor.py`
- **Port**: None
- **Description**: בודק health של המערכת כל 30 שניות, שולח התראות CRITICAL אחרי 5 כשלונות רצופים + 15 דקות cooldown
- **Environment Variables**:
  - `HEALTH_CHECK_INTERVAL=30`
  - `AUTO_FIX_ENABLE=1`
  - `TELEGRAM_SEND_ENABLE=1`

### 📡 Worker #3: Auto Scanner
- **File**: `workers/gpt_auto_suggest.py`
- **Command**: `python workers/gpt_auto_suggest.py`
- **Port**: None
- **Description**: סורק 534 שווקים כל 120 שניות, מציע trades באמצעות 7 אסטרטגיות + 5 AI brains consensus
- **Environment Variables**:
  - `SUGGEST_INTERVAL_SEC=120`
  - `SUGGEST_FUTURES=1`
  - `SUGGEST_SPOT=1`
  - `SUGGEST_GRID=1`
  - `AUTO_RUN=1`

### 📅 Worker #4: Daily Meeting 00:00
- **File**: `workers/daily_meeting.py`
- **Command**: `python workers/daily_meeting.py`
- **Port**: None
- **Description**: דוח יומי ב-00:00 UTC עם PnL, Win Rate, סיכום trades (70% עברית, 30% אנגלית)
- **Environment Variables**: None

### 📋 Worker #5: Fills Watcher
- **File**: `workers/fills_watcher.py`
- **Command**: `python workers/fills_watcher.py`
- **Port**: None
- **Description**: עוקב אחרי orders שמולאו (FILLED) כל 15 שניות, שולח התראות Telegram
- **Environment Variables**:
  - `FILLS_WATCH_ENABLE=1`
  - `FILLS_WATCH_INTERVAL_SEC=15`

### 🧠 Worker #6: GPT-5 Central Brain
- **File**: `workers/gpt5_orchestrator.py`
- **Command**: `python workers/gpt5_orchestrator.py`
- **Port**: None
- **Description**: ריכוז מוח GPT-5 - orchestration של כל ה-AI brains
- **Environment Variables**: None

### 📊 Worker #7: Position Monitor
- **File**: `workers/position_monitor.py`
- **Command**: `python workers/position_monitor.py`
- **Port**: None
- **Description**: עוקב אחרי positions פתוחות כל 30 דקות, שולח דוחות PnL, **מבטל אוטומטית את כל ה-orders כש-position נסגר** (תוקן!)
- **Environment Variables**:
  - `ENABLE_POSITION_MONITOR=1`
  - `POSITION_REPORT_INTERVAL_SEC=1800`
  - `POSITION_ALERT_LEVEL=all`

### 🔒 Worker #8: Sentinel Security
- **File**: `workers/sentinel_security.py`
- **Command**: `python workers/sentinel_security.py`
- **Port**: None
- **Description**: מעקב אבטחה ו-anomaly detection
- **Environment Variables**:
  - `SENTINEL_ENABLED=1`
  - `SENTINEL_ALERT_LEVEL=critical`

---

## 📊 Trading Strategies

AlgoGPT משתמשת ב**7 אסטרטגיות מסחר** שונות, כל אחת מותאמת למשטר שוק ספציפי.

### 1️⃣ Mean-Reversion (VWAP-Based)
- **File**: `utils/mean_reversion_strategy.py`
- **When**: CHOPPY markets, range <2%
- **Entry**: VWAP deviation >1.5 ATR
- **SL**: 0.7 ATR
- **TP**: VWAP ± 1.5 ATR
- **MinRR**: 1.05
- **MinQuality**: 5.0
- **MaxLeverage**: 6x

### 2️⃣ Scalping
- **File**: `utils/strategy_orchestrator.py`
- **When**: High volatility, strong momentum
- **Entry**: Quick in/out on 15M candles
- **SL**: 0.4 ATR
- **TP**: 1.2 RR
- **MinRR**: 1.2
- **MinQuality**: 6.0
- **MaxLeverage**: 8x

### 3️⃣ Range-Bounce
- **File**: `utils/strategy_orchestrator.py`
- **When**: Sideways markets, clear S/R levels
- **Entry**: Bounce from support/resistance
- **SL**: 0.5 ATR
- **TP**: 1.3 RR
- **MinRR**: 1.3
- **MinQuality**: 5.5
- **MaxLeverage**: 7x

### 4️⃣ Trend-Following
- **File**: `utils/strategy_orchestrator.py`
- **When**: Strong trends (ADX >25)
- **Entry**: Pullback to EMA21
- **SL**: 1.0 ATR
- **TP**: 2.0 RR
- **MinRR**: 1.8
- **MinQuality**: 6.5
- **MaxLeverage**: 5x

### 5️⃣ Breakout
- **File**: `utils/strategy_orchestrator.py`
- **When**: Consolidation → expansion
- **Entry**: Break of S/R + volume
- **SL**: 0.8 ATR
- **TP**: 2.5 RR
- **MinRR**: 2.0
- **MinQuality**: 7.0
- **MaxLeverage**: 4x

### 6️⃣ GRID Trading
- **File**: `routes/grid.py`
- **When**: Sideways markets, low volatility
- **Entry**: Grid of buy/sell orders
- **SL**: Grid-based
- **TP**: Grid-based
- **MinRR**: 1.1
- **MinQuality**: 4.5
- **MaxLeverage**: 3x

### 7️⃣ SPOT Trading
- **File**: `workers/gpt_auto_suggest.py`
- **When**: Strong uptrends, low risk
- **Entry**: SPOT buy only
- **SL**: None (HODL)
- **TP**: Manual or trailing
- **MinRR**: N/A
- **MinQuality**: 7.5
- **MaxLeverage**: 1x (no leverage)

---

## 🔬 Technical Indicators

AlgoGPT משתמשת ב**12 אינדיקטורים טכניים** לניתוח שוק מקיף:

### 📊 Momentum Indicators
1. **RSI (Relative Strength Index)** - `utils/indicators.py`
   - Period: 14
   - Oversold: <30
   - Overbought: >70

2. **MACD (Moving Average Convergence Divergence)** - `utils/indicators.py`
   - Fast: 12
   - Slow: 26
   - Signal: 9

### 📈 Trend Indicators
3. **EMA (Exponential Moving Average)** - `utils/indicators.py`
   - EMA21 (short-term)
   - EMA50 (medium-term)

4. **ADX (Average Directional Index)** - `utils/indicators.py`
   - Period: 14
   - Strong Trend: >25
   - Weak Trend: <20

### 💥 Volatility Indicators
5. **ATR (Average True Range)** - `utils/indicators.py`
   - Period: 14
   - Used for SL/TP calculation

6. **Bollinger Bands** - `utils/indicators.py`
   - Period: 20
   - Std Dev: 2

### 📊 Volume Indicators
7. **VWAP (Volume Weighted Average Price)** - `utils/indicators_ext.py`
   - Period: 50
   - Mean-reversion anchor

8. **OBV (On-Balance Volume)** - `utils/indicators_ext.py`
   - Cumulative volume

9. **Keltner Channels** - `utils/mean_reversion_strategy.py`
   - Period: 20
   - ATR multiplier: 2.0

### 🎯 Advanced Indicators
10. **QQE (Quantitative Qualitative Estimation)** - `utils/indicators_qqe.py`
    - RSI-based momentum

11. **SMC (Smart Money Concepts)** - `utils/indicators_smc.py`
    - FVG (Fair Value Gaps)
    - Sweeps (Stop Hunt)

12. **Volume** - Real-time Binance volume data

---

## 🌍 API Endpoints

AlgoGPT מספקת **50+ API endpoints** לניהול מסחר, ניטור, ו-automation.

### 🔐 Authentication

**All endpoints** require HMAC signature authentication (except public endpoints).

**Headers Required:**
```http
X-API-Key: Bearer <api_key>
X-Timestamp: <unix_timestamp>
X-Nonce: <random_hex_32>
X-Signature: <hmac_sha256_hex>
Digest: <sha256_base64_body>
```

### 📊 Core Endpoints

#### Health & Status
```http
GET  /health              - Basic health check
GET  /readyz              - Readiness probe
GET  /api/info            - System information
```

#### Market Data
```http
GET  /price/{symbol}            - Latest price
GET  /scan/public-topk          - Top market opportunities
GET  /context/batch             - Batch market context
```

#### Trading
```http
POST /alerts/ingest             - Trade proposal ingestion (HMAC required)
POST /trade/execute             - Manual trade execution
GET  /executor/positions        - Active positions
POST /position-ops/manage-once  - Manage open positions
```

#### AI & Analysis
```http
POST /ai/suggest                - AI trade suggestions
GET  /ai/leaderboard            - AI model performance
GET  /ai/performance            - Detailed AI metrics
```

#### PnL & Reports
```http
GET  /pnl/summary              - P&L summary
GET  /pnl/daily                - Daily P&L report
GET  /pnl/history              - Historical P&L
```

#### Telegram
```http
POST /telegram/webhook         - Telegram bot webhook
POST /telegram/callback        - Interactive button callbacks
```

---

## 🔐 Security (HMAC Signature)

AlgoGPT uses **HMAC-SHA256 signatures** for all critical API calls to ensure authenticity and prevent replay attacks.

### 🔑 Signature Flow

```python
# 1. Generate timestamp + nonce
timestamp = str(int(time.time()))
nonce = secrets.token_hex(16)

# 2. Hash request body
body_hash = hashlib.sha256(body_bytes).hexdigest()

# 3. Build signature message
message = f"{timestamp}.{nonce}.{body_hash}"

# 4. Generate HMAC signature
secret = os.getenv("WEBHOOK_HMAC_SECRET")  # or OPS_SIGN_SECRET
signature = hmac.new(
    secret.encode(),
    message.encode(),
    hashlib.sha256
).hexdigest()

# 5. Send headers
headers = {
    "X-Timestamp": timestamp,
    "X-Nonce": nonce,
    "X-Signature": signature,
    "Digest": base64.b64encode(hashlib.sha256(body_bytes).digest())
}
```

### 🛡️ Anti-Replay Protection

- **Timestamp validation**: Requests older than 300 seconds are rejected
- **Nonce tracking**: Each nonce can only be used once
- **Constant-time comparison**: Prevents timing attacks

### 🔒 Supported Secrets (Priority Order)

1. `ALERTS_INGEST_HMAC_SECRET`
2. `WEBHOOK_HMAC_SECRET`
3. `ALERTS_HMAC_SECRET`
4. `OPS_SIGN_SECRET`
5. `ALERTS_WEBHOOK_SECRET`
6. `SECRET` (fallback)

**Hex Keys**: Set `<SECRET>_KEY_IS_HEX=1` if secret is hex-encoded.

---

## 📁 Project Structure

```
AlgoGPT/
├── main.py                    # FastAPI server
├── gunicorn_conf.py          # Gunicorn config
├── requirements.txt          # Python dependencies
├── replit.md                 # Project summary
├── README.md                 # This file
│
├── workers/                  # Background workers (8)
│   ├── auto_health_monitor.py    # Health monitoring
│   ├── gpt_auto_suggest.py       # Market scanner
│   ├── fills_watcher.py          # Order fills tracker
│   ├── position_monitor.py       # Position tracking + order cleanup
│   ├── daily_meeting.py          # Daily reports
│   ├── gpt5_orchestrator.py      # GPT-5 orchestrator
│   ├── sentinel_security.py      # Security monitoring
│   └── n8n_bridge.py             # N8N integration
│
├── routes/                   # FastAPI routes
│   ├── alerts.py             # Trade alert ingestion
│   ├── trade.py              # Trade execution
│   ├── grid.py               # GRID trading
│   ├── position_ops.py       # Position management
│   ├── telegram_webhook.py   # Telegram webhooks
│   └── dashboard.py          # UI dashboard
│
├── utils/                    # Core utilities
│   ├── ai_decision_maker.py       # 5 AI brains + consensus engine
│   ├── ai_post_trade_review.py   # Post-trade AI reviews
│   ├── ai_trade_scorer.py        # Multi-AI scoring
│   ├── anthropic_client.py       # Claude client
│   ├── gemini_client.py          # Gemini client
│   ├── xai_client.py             # Grok client
│   ├── strategy_orchestrator.py  # 7 strategies orchestrator
│   ├── mean_reversion_strategy.py
│   ├── regime_detector_v2.py     # Market regime detection
│   ├── market_intelligence.py    # Multi-TF analysis
│   ├── indicators.py             # 12 technical indicators
│   ├── indicators_ext.py         # Extended indicators (VWAP, OBV)
│   ├── indicators_smc.py         # Smart Money Concepts
│   ├── indicators_qqe.py         # QQE indicator
│   ├── binance_client.py         # Binance API wrapper
│   ├── security.py               # HMAC signature verification
│   ├── auto_executor.py          # Trade execution engine
│   ├── trade_manager.py          # Position management
│   └── portfolio_intelligence.py # Portfolio analysis
│
├── data/                     # Data storage
│   ├── ai_reviews/           # AI trade reviews
│   ├── backtest/             # Backtest results
│   └── cache/                # Cached data
│
└── monitoring/               # Monitoring & metrics
    └── grafana/              # Grafana dashboards
```

---

## 🚀 Installation & Setup

### Prerequisites

- Python 3.11+
- PostgreSQL (Neon recommended)
- Binance Futures Account
- API Keys: OpenAI, Anthropic, Google (Gemini), DeepSeek, XAI (Grok)

### 1. Clone Repository

```bash
git clone <repo_url>
cd AlgoGPT
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create `.env` file:

```bash
# Binance API
BINANCE_API_KEY=<your_binance_api_key>
BINANCE_API_SECRET=<your_binance_api_secret>

# Database
DATABASE_URL=postgresql://user:pass@host/db

# AI API Keys
OPENAI_API_KEY=<your_openai_key>
ANTHROPIC_API_KEY=<your_anthropic_key>
GEMINI_API_KEY=<your_gemini_key>
DEEPSEEK_API_KEY=<your_deepseek_key>
XAI_API_KEY=<your_xai_key>

# Telegram
TELEGRAM_BOT_TOKEN=<your_bot_token>
TELEGRAM_CHAT_ID=<your_chat_id>

# Security
WEBHOOK_HMAC_SECRET=<random_32_byte_hex>
OPS_SIGN_SECRET=<random_32_byte_hex>

# Trading Config
EXECUTE_TRADES=1
AUTO_RUN=1
ENABLE_MULTI_AI_CONSENSUS=1
```

### 4. Run Server

```bash
# Development
python main.py

# Production
gunicorn -c gunicorn_conf.py main:app
```

### 5. Start Workers

```bash
# Terminal 1: Auto Scanner
python workers/gpt_auto_suggest.py

# Terminal 2: Health Monitor
python workers/auto_health_monitor.py

# Terminal 3: Position Monitor
python workers/position_monitor.py

# Terminal 4: Fills Watcher
python workers/fills_watcher.py
```

---

## 📊 Performance Metrics

### Target Metrics (v9.0)
- **Daily Trades**: 4-10 high-quality trades
- **Win Rate**: ≥47%
- **Risk/Reward**: ≥1.3:1
- **Max Drawdown**: <10%
- **Uptime**: 99.9%

### AI Consensus Performance
- **Avg Consensus Time**: ~3-5 seconds
- **AI Agreement Rate**: ~60-80%
- **Quality Filter**: Avg score ≥5.8/10 (regime-based)

---

## 🗺️ Roadmap

### ✅ Completed (v9.0)
- [x] 5-brain AI consensus engine
- [x] Regime-based dynamic parameters
- [x] 7 trading strategies
- [x] Auto order cleanup on position close
- [x] HMAC signature security
- [x] 534 markets scanning

### 🚧 In Progress
- [ ] Machine learning trade outcome prediction
- [ ] Advanced portfolio optimization
- [ ] Multi-exchange support (Bybit, OKX)

### 📅 Future Plans
- [ ] Options trading support
- [ ] Copy trading API
- [ ] Mobile app (iOS/Android)

---

## 📝 Auto-Update Mechanism

This README.md is **automatically updated** on every code change using:

1. **Pre-commit hook** (`.git/hooks/pre-commit`)
2. **GitHub Action** (`.github/workflows/update-readme.yml`)

**Auto-detected metrics:**
- Number of AI brains
- Number of workers
- Number of strategies
- Number of indicators
- Version number
- Last update timestamp

---

## 📄 License

This project is **private and proprietary**. All rights reserved.

---

## 📞 Contact & Support

For questions or support, contact the development team.

---

<div align="center">

**Made with ❤️ by AlgoGPT Team**

**Last Updated**: 2025-01-06 | **Version**: 9.0.0

</div>
