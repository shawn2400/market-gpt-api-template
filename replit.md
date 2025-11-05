# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an algorithmic trading platform built with FastAPI and Python, designed for 24/7 live Binance Futures trading. It features automated market scanning across 530+ symbols, AI-powered trade decisions via GPT-5, multi-AI consensus, GRID trading options, and professional automated dynamic management. The platform targets 4-10 high-quality daily trades with significant profits and minimal losses, aiming for a fully self-adaptive trading engine with dynamic capital optimization and complete data persistence.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations.

## System Architecture

### UI/UX
The dashboard UI is located in `static/dashboard/`. Telegram notifications are enhanced with HTML formatting, emojis, and inline interactive buttons for improved user experience and visual tagging of trade types.

### Technical Implementations
The core application uses FastAPI (`main.py`) and Gunicorn. Functionalities are modularized into `routes/` for API endpoints and `utils/` for common functions. Policies are managed via YAML files in `policies/`.

**Recent Upgrades (MetaBrain v8.0 - Nov 5, 2025):**
-   **Fills Watcher Worker** (✅ PRODUCTION-READY - Nov 5, 2025): Automated SL/TP/BE/Trailing management for all open positions. Dedicated _TradeManagerThread runs manage_open_trades() every 60 seconds independently of WATCHLIST - queries Binance directly for all open positions (positionAmt != 0). Enhanced logging with print statements for visibility. Worker monitors fills, sets protective stops, manages BE Guard, and profit locking. Now running 24/7 in Procfile. **Full Hedge Mode Support** (Nov 5, 2025): Complete fix for Binance Hedge Mode API requirements - modify_stop_loss() and modify_take_profit() now correctly use positionSide parameter without reduceOnly flag, with positionSide-filtered qty lookup and order cancellation to handle simultaneous LONG/SHORT positions on same symbol (fixes Binance error codes -4061, -1106). System now supports dual-sided hedging with independent SL/TP for each leg.
-   **Budget Optimization** (✅ PRODUCTION-READY - Nov 5, 2025): BUDGET_MAX_USDT reduced from $150 to $30 per trade, enabling 5-6 simultaneous positions with $166 equity (vs. 1 trade previously). Dynamic budget system still active with quality multipliers.
-   **Enhanced Margin Guard** (✅ PRODUCTION-READY - Nov 5, 2025): Auto-scanner checks available balance BEFORE starting each scan cycle. If available < BUDGET_MIN_USDT, entire cycle is PAUSED to prevent proposal spam when funds locked in open positions. Detailed error logging shows exact balance, URLs, and failure reasons for debugging.
-   **Telegram Auto-Execution Toggle** (✅ PRODUCTION-READY - Nov 5, 2025): One-click toggle between APPROVAL mode and FULL AUTO mode via Telegram `/auto` command. Settings persist in database, no restart needed. In FULL AUTO mode, all trade proposals execute immediately without approval buttons.
-   **Enhanced Error Logging** (Nov 5, 2025): Comprehensive error tracking in pos_events.py and gpt_auto_suggest.py with detailed messages showing symbol, side, URLs, and exception types for faster debugging. Production-grade INFO-level logging in trade_manager.py with emoji markers for SL/TP placement success/failure states.
-   **Lowered Filtering Thresholds**: MIN_RR reduced from 1.45 to 1.15, Quality scores from 0.70 to 0.50, enabling more trades in all market conditions
-   **Strategy Orchestrator**: Intelligent auto-selection of GRID/Scalping/Momentum/Range-Bounce/Mean-Reversion based on real-time market regime (CHOPPY/SIDEWAYS/TRENDING/VOLATILE/NEUTRAL)
-   **Mean-Reversion Strategy** (PRODUCTION-READY - Nov 5, 2025): ✅ Fully operational deterministic VWAP-based strategy for CHOPPY/NEUTRAL markets with range <2%. Uses real Binance OHLCV data (180 candles @ 15m) for accurate VWAP + Keltner Bands calculations. Entry at VWAP ± 0.3×ATR (lowered from 1.5×), TP at VWAP ± 0.2-0.3×ATR, SL at entry ± 0.7×ATR. Achieves RR ≥1.47-3.67 (well above minimum 1.05 threshold). Successfully generating 7+ proposals per scan cycle.
-   **Real OHLCV Integration**: Mean-Reversion strategy fetches data directly from Binance API instead of relying on Context API (avoids DataFrame serialization issues)
-   **VWAP & Keltner Bands Indicators**: Added to `utils/indicators.py` for mean-reversion calculations
-   **Adaptive RR Thresholds**: Dynamic Risk/Reward requirements per strategy - GRID=1.10, Scalping=1.10, Mean-Reversion=1.05 (with 70%+ win rate), Range-Bounce=1.15, Momentum=1.25, Breakout=1.40
-   **Permissive Fallbacks**: System now allows trading with incomplete data (DISABLE_PERMISSIVE_FALLBACKS=0) instead of blocking everything

**Core Features:**
-   **Automated Trading Modes**: Supports MARKET, HYBRID, and FULL AUTO execution (Telegram approval DISABLED for instant trades).
-   **Live Trade Management**: Dynamic management of open positions with TP, SL, BE logic, and ATR-based trailing stops.
-   **Market Scanner**: Autonomous worker performs multi-timeframe technical analysis every 60 seconds across 531 Binance Futures markets.
-   **AI-Powered Proposals**: **5 AI providers** (GPT-5, Gemini 2 Pro, DeepSeek, Grok, Claude) generate trade proposals with **ADAPTIVE Risk/Reward thresholds** - CHOPPY=1.1, SIDEWAYS=1.15, TRENDING=1.25, VOLATILE=1.4. Multi-AI consensus with dynamic weighting based on performance.
-   **GRID Trading**: Integrated FUTURES GRID trading for choppy/sideways markets (**minimum range ≥2%**, lowered from 4% for more opportunities).
-   **Mean-Reversion Strategy**: NEW (Nov 5, 2025) - Deterministic math-based strategy for CHOPPY/NEUTRAL markets with range <2%. Uses VWAP deviation (1.5× ATR) for entries, targeting mean-reversion with 70-80% win rate. Operates independently of GPT for consistent execution in low-volatility conditions.
-   **Scalping & Range-Bounce Strategies**: Aggressive short-term trades in CHOPPY markets with tight stops and RR≥1.1 for frequent small wins.
-   **Risk Management**: Implements quality filters, dynamic filters, liquidity checks, cooldown periods, daily trade caps, and a circuit breaker for daily loss limits.
-   **FULL AUTO MODE**: Telegram notifications ONLY (no approval required). System executes trades instantly based on AI analysis.
-   **Dynamic Position Management**: Features ATR Trailing, Multi-level TP ladder, and Dynamic Position Sizing.
-   **Auto-Flip**: Dynamically adapts to market conditions, proposing LONG or SHORT trades with multi-system validation.
-   **Self-Adaptive Trading Engine**: Incorporates Market Intelligence (regime, mood, volatility detection), Adaptive AI Prompts with scalping strategies, and Portfolio Intelligence (exposure management, correlation prevention).
-   **Dynamic Budget System** (ENABLED): Each trade budget calculated in real-time based on:
    - 1% of account equity (configurable via BUDGET_PCT_OF_EQUITY)
    - Trade quality multiplier: 0.7x (quality 4/10) to 1.8x (quality 9+/10)
    - Volatility adjustment: Reduces budget in high ATR markets for safety
    - Floor: $10 USDT minimum per trade
    - Ceiling: $100 USDT maximum per trade
    - **Result**: No fixed position sizes - every trade sized optimally for its risk/reward profile
-   **Dynamic SL/TP Calculation**: 
    - Stop Loss: ATR-based (adapts to market volatility)
    - Take Profit: RR-based (1.1-1.4x depending on market regime)
    - **Result**: No template stops - every trade has custom risk parameters
-   **Complete Data Persistence**: All critical data, including trade sizing, market states, and performance records, is saved to a PostgreSQL database.

**Security & Authentication:**
-   Uses Bearer Token (`X-API-Key`) and HMAC Signature.
-   Includes anti-replay protection and mandatory Telegram approval.

### AI Brains System (MetaBrain v7.5)
AlgoGPT integrates 9+ specialized AI systems with **5 AI providers** for consensus-based decisions:

**Multi-AI Consensus Engine (5 Providers):**
-   **OpenAI GPT-5** (gpt-5-2025-08-07): Master AI orchestrator, high-level analysis
-   **Google Gemini 2 Pro** (gemini-2.0-flash-exp): Fast reasoning, multi-modal analysis
-   **DeepSeek Chat**: Parameter optimization, entry/TP/SL refinement
-   **AI-X Grok**: System health monitoring, anomaly detection
-   **Claude Sonnet 3.5** (optional): Additional consensus validation

**Specialized AI Systems:**
-   **GPT Auto Suggest**: Autonomous market scanner with multi-timeframe analysis (15M/1H/4H) and trade proposals
-   **Multi-AI Consensus Scorer**: Combines 5 AI providers with dynamic weighting based on historical performance per market regime
-   **Adaptive Prompt Engine**: Generates dynamic AI prompts optimized for current market regime (CHOPPY/SIDEWAYS/TRENDING/VOLATILE)
-   **Market Intelligence Brain**: Real-time market regime detection, volatility analysis, mood assessment
-   **Portfolio Intelligence**: Exposure management, position limits, correlation prevention
-   **News Sentiment Analyzer**: Crypto news headline analysis for market sentiment
-   **Auto-Flip System**: Directional decisions (LONG/SHORT) using multi-timeframe weighted analysis

### Validation & Safety Infrastructure (v2.0)
Includes a **Validation Pipeline** (historical backtesting with walk-forward testing), **Fail-Closed Decision Gates** (Dual Confirmation: Quant ∧ AI ∧ Risk), **Data-Driven Monte Carlo** simulations, a **Live Health Monitor**, and **Circuit Breakers** (daily drawdown, consecutive loss limits).

### Production Enhancements (Phase 1)
All 38 tasks completed, including AI performance tracking (dynamic model weighting, prediction logging, outcome tracking, feedback dataset for fine-tuning, AI leaderboard), database hardening (10 tables for slippage, circuit breaker state, market states, audit logs, AI predictions, etc.), and enhanced monitoring & security (real-time P&L, tiered alerting, rate limiting, log masking, audit trail, IP throttling, comprehensive testing).

### Deployment Architecture

**Production Environment (PRIMARY - 24/7):**
The system runs on **Render.com** - this is the REAL production environment:
-   **Service**: algogpt-docker ($7/month Web Service)
-   **Workers**: 8 background workers configured in Procfile (scanner, health, gpt5, n8n, positions, sentinel, fills)
-   **Domain**: https://algogpt-docker.onrender.com
-   **Dashboard**: https://algogpt-docker.onrender.com/static/dashboard/index.html
-   **Repository**: Connected to GitHub repo `market-gpt-api-template`
-   **Auto-Deploy**: Every push to `main` triggers automatic deployment
-   **Environment**: All 14 required secrets configured via Render dashboard
-   **Database**: Managed PostgreSQL on Render (production data)
-   **Uptime**: 24/7 continuous operation - THIS IS WHERE REAL TRADING HAPPENS

**Development Environment (Replit - Dev Tool Only):**
Replit is used ONLY for development and testing:
-   **Purpose**: IDE, code editing, debugging, testing changes
-   **Database**: Separate development PostgreSQL (NOT production data)
-   **Workers**: Run locally for testing only
-   **Important**: Changes made on Replit do NOT affect production until pushed to GitHub and deployed to Render
-   **Workflow**: Edit code on Replit → Push to GitHub → Auto-deploy to Render → Production updated

**Independence from Replit:**
-   All code is platform-agnostic and runs on any Python environment
-   No dependency on Replit-specific features (REPL_SLUG, etc. are optional)
-   System fully functional on Render without any Replit infrastructure
-   Replit Agent Bridge worker disabled on non-Replit environments

## External Dependencies

-   **Binance Futures API**: Market data, order execution, account management.
-   **OpenAI API**: GPT-5 (gpt-5-2025-08-07) for AI trade proposals and market analysis.
-   **Google Gemini API**: Gemini 2 Pro (gemini-2.0-flash-exp) for fast multi-modal reasoning.
-   **DeepSeek API**: AI provider for trade optimization and multi-AI consensus.
-   **AI-X/Grok API**: AI provider for system supervision and consensus.
-   **Anthropic Claude API** (optional): Claude Sonnet 3.5 for additional consensus validation.
-   **Telegram Bot API**: Notifications, approval workflows, interactive callbacks.
-   **N8N Workflow Automation**: External workflow integration, news ingestion.
-   **Gunicorn**: Production-grade WSGI HTTP server.
-   **PostgreSQL**: Persistent data storage.
-   **SQLAlchemy**: ORM for database interaction.
-   **Psycopg2**: PostgreSQL adapter.
-   **psutil**: System and process monitoring.
-   **httpx**: Async HTTP client for AI provider API calls.
-   **scipy**: Scientific computing for statistical analysis.
-   **numpy**: Numerical computing for simulations and metrics.