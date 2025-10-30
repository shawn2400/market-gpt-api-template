# AlgoGPT - Algorithmic Trading Platform

## Overview

AlgoGPT is a comprehensive algorithmic trading platform built with FastAPI and Python. It provides real-time trading orchestration for Binance Futures with features including:

- **Trading Operations**: Automated trade execution with MARKET, HYBRID, and AUTO modes
- **Live Trade Management**: Advanced position management with TP/SL, trailing stops, break-even logic
- **Scanner & Analytics**: Multi-timeframe technical analysis with quality scoring
- **Risk Management**: Daily caps, position sizing, and pre-trade validation
- **Operations Approval**: Secure ticket-based approval system with HMAC authentication
- **API & Monitoring**: RESTful API with Prometheus metrics and health endpoints

**Current Status**: ✅ **FULLY OPERATIONAL** - Live trading mode enabled with all features active

## System Status

### ✅ Active Components
1. **AlgoGPT Server** (Port 5000) - Main FastAPI application
2. **Auto Scanner** - Runs every 60 seconds, scanning Binance Futures markets
3. **Context API** - Multi-timeframe technical analysis engine
4. **OpenAI Integration** - AI-powered trade proposal generation
5. **Telegram Bot** - Approval workflow and real-time notifications
6. **Dynamic Position Manager** - Automated TP/SL/BE/Trail management

### 🔑 Configured Secrets (Replit Secrets)
- `BINANCE_API_KEY` ✅
- `BINANCE_API_SECRET` ✅
- `OPENAI_API_KEY` ✅
- `TELEGRAM_BOT_TOKEN` ✅
- `TELEGRAM_CHAT_ID` ✅

### 🚀 Active Workflows

**AlgoGPT Server**:
```bash
AUTO_RUN=1 EXECUTE_TRADES=1 TRADE_AUTO_SUGGEST=1 SUGGEST_FUTURES=1 
ALLOW_MANAGE_OPEN_TRADES=1 PAUSE_AUTO_RUN=0 MANAGER_ENABLE=1 
TRADE_MANAGER_ENABLE=1 TELEGRAM_SEND_ENABLE=1 APPROVAL_ENABLED=1 
REQUIRE_TELEGRAM_APPROVAL=1 AUTO_OPEN_ON_APPROVE=1 
SMART_MANAGE_ON_APPROVE=1 TRAIL_ENABLE=1 BE_GUARD_ENABLE=1 
PORT=5000 gunicorn -c gunicorn_conf.py main:app
```

**Auto Scanner**:
```bash
TRADE_AUTO_SUGGEST=1 SUGGEST_FUTURES=1 SUGGEST_INTERVAL_SEC=60 
CONTEXT_URL=https://<replit-domain> 
ALERT_INGEST_URL=https://<replit-domain>/alerts/trade-ingest 
python workers/gpt_auto_suggest.py
```

## Project Architecture

### Backend (FastAPI)
- **Main Application**: `main.py` - Core FastAPI app with all routes and business logic
- **Configuration**: `gunicorn_conf.py` - Gunicorn server configuration
- **Workers**: `workers/gpt_auto_suggest.py` - Autonomous market scanner

### Key Components
- **Routes**: Organized in `routes/` directory for modular endpoint management
  - `routes/context.py` - Multi-timeframe technical analysis API
  - `routes/alerts.py` - Trade ingestion with enhanced Telegram notifications
  - `routes/telegram_callbacks.py` - Telegram callback handler (approve/reject buttons)
  - `routes/telegram_bot.py` - Telegram bot integration
- **Utilities**: Common functions in `utils/` for trading, analysis, and integration
  - `utils/hmac_utils.py` - HMAC signing and idempotency
  - `utils/auth.py` - Bearer token authentication
  - `utils/trade_executor.py` - Live order execution
- **Policies**: YAML-based configuration in `policies/` for dynamic strategy management
- **Static Files**: Dashboard UI in `static/dashboard/`

### Database & Storage
- **Trades Log**: JSON-based storage in `data/trades_log.json`
- **Redis**: Optional (currently not configured, using in-memory fallback)

## How It Works

### 1. Auto Scanner Cycle (Every 60 seconds)
1. Loads watchlist from `data/watchlist.json` (18 symbols)
2. Builds smart symbol pool (top quality + BTC/ETH anchors)
3. Fetches multi-timeframe context via `/context/batch` API
4. Calls OpenAI GPT-4 to analyze each symbol and propose trades
5. Applies strict quality filters (RR > 1.6-1.9, success_pct > 70%)
6. Checks liquidity gates to avoid slippage
7. Applies cooldown (12 min) and deduplication (24h) filters
8. Sends approved proposals to `/alerts/trade-ingest`

### 2. Telegram Approval Workflow (Enhanced with Rich UI)
1. Trade proposal arrives at `/alerts/trade-ingest`
2. System generates approval ticket with unique ID
3. **Rich Telegram message sent with**:
   - ✅ **Green APPROVE** button & ❌ **Red REJECT** button
   - 💎 Full trade details: Entry price, SL, TP1/TP2/TP3 levels
   - ⭐ Quality score (0-10) & Success probability (%)
   - 📊 Direction (LONG/SHORT), Leverage, Budget, Quantity
   - 📝 AI-generated strategy reasoning
   - ⏱️ Timeframe & comprehensive analysis
4. User clicks **✅ APPROVE** → `/telegram/callback` → `/ops/approve/signed`
5. Ticket validated with HMAC, trade executed on Binance Futures
6. Position opened, dynamic management (TP/SL/BE/Trail) activated automatically
7. Telegram buttons removed, confirmation message sent

### 3. Dynamic Position Management
- **Break-Even Guard**: Moves SL to entry + offset when price moves favorably
- **ATR Trailing**: Dynamic trailing stop based on market volatility
- **Multi-Target TP**: Scales out at TP1, TP2, TP3 levels
- **Smart Manager**: Combines BE + Trail + partial exits automatically

## API Endpoints

### Public Endpoints
- `GET /` - Service info and configuration
- `GET /health` - Health check
- `GET /readyz` - Readiness check
- `GET /docs` - Interactive API documentation (Swagger UI)
- `GET /redoc` - Alternative API documentation

### Protected Endpoints (require API_BEARER_TOKEN via X-API-Key header)
- `POST /context/batch` - Multi-symbol technical analysis
- `POST /alerts/trade-ingest` - Trade proposal ingestion (HMAC signed)
- `POST /ops/ticket` - Create operations ticket
- `POST /ops/approve` - Approve operation
- `GET /ops/ui` - Operations UI
- Various trading, analysis, and management endpoints

## Security

### Authentication Methods
1. **Bearer Token**: Include `X-API-Key` header with `API_BEARER_TOKEN` value
2. **HMAC Signature**: For critical operations, requires X-Timestamp, X-Nonce, X-Signature headers

### Safety Features
- ✅ **Live Trading ENABLED** with strict quality filters
- ✅ Multi-layer risk management (RR, success_pct, liquidity, cooldown)
- ✅ Telegram approval required before opening positions
- ✅ Daily trade cap (2 trades per cycle max)
- ✅ Deduplication prevents duplicate proposals (24h TTL)
- ✅ Anti-replay protection (in-memory, upgradeable to Redis)

## Development

### File Structure
```
.
├── main.py                    # Main FastAPI application
├── gunicorn_conf.py          # Gunicorn configuration
├── requirements.txt          # Python dependencies
├── workers/
│   └── gpt_auto_suggest.py   # Auto scanner worker
├── routes/
│   ├── context.py            # Technical analysis API
│   ├── alerts.py             # Trade ingestion
│   └── telegram_bot.py       # Telegram workflow
├── utils/
│   ├── auth.py               # Authentication
│   ├── hmac_utils.py         # HMAC utilities
│   └── trade_executor.py     # Order execution
├── data/
│   ├── watchlist.json        # Monitored symbols
│   └── trades_log.json       # Trade history
└── static/                   # Dashboard UI
```

## Monitoring

- **Metrics**: Available at `/metrics` (requires Bearer token)
- **Health Checks**: `/health`, `/readyz`
- **Logs**: Workflow console shows real-time activity
- **Telegram**: Real-time notifications for proposals, executions, and position updates

## Key Features

### 🔄 Auto-Flip (Dynamic LONG/SHORT Analysis)
The system **automatically adapts to market conditions every 60 seconds**:
- Scanner analyzes each symbol independently
- AI decides LONG or SHORT based on real-time market data
- If market reverses, AI naturally proposes opposite direction
- No manual intervention needed - system "breathes with the market"
- Example: BTC was LONG → Market weakens → Next cycle AI suggests SHORT

### 📱 Enhanced Telegram Notifications
Every trade proposal includes:
- **Visual Buttons**: ✅ Green APPROVE / ❌ Red REJECT / 📊 Details
- **Complete Trade Info**: Entry, SL, TP1/TP2/TP3, Leverage, Budget
- **AI Analysis**: Quality score, success probability, strategy reasoning
- **Professional Format**: HTML formatting with emojis and clear structure
- **Interactive**: One-click approval, instant execution feedback

### 🎯 Quality Filters (Why Few Trades?)
The system uses **strict multi-layer filters** to protect capital:
1. **Risk/Reward Ratio** > 1.6-1.9 (minimum)
2. **AI Success Probability** > 70%
3. **Liquidity Gates**: Sufficient volume to avoid slippage
4. **Trend Filters**: ADX checks to avoid choppy markets
5. **Cooldown**: 12 minutes between trades on same symbol
6. **Deduplication**: Won't send duplicate setups (24h TTL)

**This is intentional!** Better to wait for high-quality setups than trade mediocre ones.

## Recent Changes

- **2025-10-30**: Smart Portfolio Management & Monitoring System
  - ✅ **Position Monitor Worker** - Reports every 30-60 minutes with PNL updates
  - ✅ **Smart Budget Allocation** - Automatically splits wallet across 2-4 trades
  - ✅ **Score-Based Leverage** - Higher quality trades get more leverage (up to 1.5x boost)
  - ✅ **Portfolio Manager** - Prevents over-trading, manages concurrent positions
  - ✅ **Consolidated Reports** - Single Telegram message every 30 min with all trades
  - ✅ **Grid Trading Integration** - Grid executor, planner, and tracker modules ready
- **2025-10-30**: Enhanced Telegram notifications with inline buttons
  - ✅ Added rich HTML formatting with comprehensive trade details
  - ✅ Implemented inline keyboard (APPROVE/REJECT/Details buttons)
  - ✅ Registered `routes/telegram_callbacks` for button handling
  - ✅ Callback flow: Button click → HMAC-signed approval → Binance execution
  - ✅ Support for entry/sl/tp1/tp2/tp3 as float or dict format
  - ✅ Auto-flip already working - AI analyzes independently each cycle
- **2025-10-30**: Full live trading deployment
  - ✅ Fixed LSP type errors in workers/gpt_auto_suggest.py and utils/hmac_utils.py
  - ✅ Registered routes/context.py and routes/alerts.py in main.py
  - ✅ Added API key authentication to Auto Scanner → Context API calls
  - ✅ Configured all secrets in Replit Secrets (Binance, OpenAI, Telegram)
  - ✅ Both workflows running successfully (AlgoGPT Server + Auto Scanner)
  - ✅ OpenAI integration verified - GPT-4 analyzing markets
  - ✅ Context API verified - returning multi-timeframe indicators
  - ✅ System operational - waiting for high-quality trade setups

## Current Behavior

The system is **fully operational** and running in live mode:

1. ✅ **Auto Scanner** analyzes 7-8 symbols every 60 seconds
2. ✅ **OpenAI** successfully called for AI-powered analysis
3. ✅ **Context API** provides technical indicators (RSI, EMA, ATR, volume regime, etc.)
4. ✅ **Quality Filters** working correctly - rejecting low-quality setups
5. ⏳ **Waiting for Quality Setup** - 0 trades accepted so far (filters working as intended)

The scanner is rejecting proposals because current market conditions don't meet the strict criteria:
- RR (Risk/Reward) must be > 1.6-1.9
- Success probability must be > 70%
- Liquidity must support position size
- No choppy/sideways markets (ADX filters)
- Cooldown prevents over-trading same symbol

This is **good behavior** - it means the risk management is protecting capital and only high-probability setups will be approved.

## Troubleshooting

### No trades being generated
This is **expected and correct**. The system has strict quality filters and will only propose trades when:
- Market shows clear trend or breakout
- Risk/Reward ratio exceeds minimum thresholds
- AI assigns high success probability (>70%)
- Liquidity is sufficient for the position size

You can monitor the Auto Scanner logs to see analysis activity.

### Telegram not receiving messages
- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set correctly
- Check that bot is started (send `/start` to your bot)
- Review logs for Telegram API errors

### Orders not executing
- Verify Binance API keys have Futures trading permissions
- Check daily trade limits haven't been reached
- Ensure sufficient USDT balance in Futures wallet

## Links

- **API Documentation**: `/docs` (Swagger UI)
- **Alternative Docs**: `/redoc`
- **Health Check**: `/health`
- **Webview**: Replit provides public URL for the dashboard

## Notes

This is a **LIVE algorithmic trading system**. All features are enabled and the bot is actively scanning markets. Trading involves significant financial risk. The system uses strict quality filters and Telegram approval workflow to ensure only high-probability trades are executed. Monitor the workflow logs and Telegram bot for real-time activity.
