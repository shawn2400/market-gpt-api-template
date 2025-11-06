# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an algorithmic trading platform designed for 24/7 live Binance Futures trading. It automates market scanning across 530+ symbols, leveraging AI-powered trade decisions via GPT-5 and multi-AI consensus. The platform incorporates GRID trading, dynamic capital management, and a self-adaptive trading engine with complete data persistence. AlgoGPT aims for 4-10 high-quality daily trades, focusing on profitability, minimal losses, and autonomous operation. MetaBrain v8.0 introduces fully autonomous regime-driven trading with 3-layer database resilience for production stability.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations.

## System Architecture

### UI/UX
The system provides a dashboard UI and enhanced Telegram notifications, utilizing HTML formatting, emojis, and inline interactive buttons for improved user experience.

### Technical Implementations
The core application is built with FastAPI and Gunicorn, featuring modularized functionalities for API endpoints and common utilities. Policies are managed via YAML files.

**Core Features:**
-   **Automated Trading Modes**: Supports MARKET, HYBRID, and FULL AUTO execution.
-   **Live Trade Management**: Dynamic management of open positions with TP, SL, BE logic, and ATR-based trailing stops.
-   **Market Scanner**: Autonomous worker performs multi-timeframe technical analysis across 531 Binance Futures markets.
-   **AI-Powered Proposals**: Utilizes 5 AI providers (GPT-5, Gemini 2 Pro, DeepSeek, Grok, Claude) for consensus-based trade decisions with adaptive Risk/Reward thresholds based on market regime.
-   **GRID Trading**: Integrated FUTURES GRID trading for choppy/sideways markets.
-   **Mean-Reversion Strategy**: Deterministic VWAP-based strategy for choppy/neutral markets.
-   **Scalping & Range-Bounce Strategies**: Aggressive short-term strategies for choppy markets.
-   **Risk Management**: Implements quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
-   **Dynamic Budget System**: Trade budgets are calculated in real-time based on account equity, trade quality, volatility, and defined floors/ceilings.
-   **Dynamic SL/TP Calculation**: Stop Loss is ATR-based, and Take Profit is RR-based, adapting to market volatility and regime.
-   **Complete Data Persistence**: All critical data is saved to a PostgreSQL database.

**MetaBrain v8.0 Enhancements:**
-   **Database Resilience**: 3-layer protection including auto-pause prevention, exponential backoff retries, and fallback queue to JSON.
-   **Dynamic Regime System**: Four market regimes (TRENDING, CHOPPY, VOLATILE, SIDEWAYS) with context-adaptive strategy switching and regime-specific parameter adjustments.
-   **Zero-Gap SL Manager**: Ensures continuous protection during stop-loss updates.
-   **TP Ladder System**: Multi-level take profits with configurable weights.
-   **Daily Trading Reports**: Comprehensive Telegram reports with PnL, Win Rate, and trade summaries.

**MetaBrain v8.0 Hotfix (2025-11-06):**
-   **Neon Auto-Resume**: Automatically resumes Neon PostgreSQL endpoint via API when it auto-pauses, preventing database unavailability.
-   **Binance Hedge Mode Enforcement**: Ensures `dualSidePosition=true` is set before trading, preventing APIError -4061 (position side mismatch).
-   **Dynamic TP Ladder Fix**: Prevents negative TP prices with proper tick size quantization and price validation.
-   **Order Params Safety**: Intelligent order parameter building that prevents -4061 and -1106 errors by correctly managing `positionSide` and `reduceOnly`.
-   **Telegram Digest Consolidation**: All non-critical notifications batched into 30-minute digests (health: 3x daily at 08:00, 16:00, 00:00 Israel; trades: every 30 min if significant events).
-   **ENV Validation**: Fail-fast validation of critical API keys and configuration with clear logging of missing providers.

**Security & Authentication:**
-   Uses Bearer Token (`X-API-Key`) and HMAC Signature, with anti-replay protection and mandatory Telegram approval.

### AI Brains System
The system integrates 9+ specialized AI systems with 5 AI providers for consensus-based decisions:
-   **Multi-AI Consensus Engine**: Orchestrated by OpenAI GPT-5, supported by Google Gemini 2 Pro, DeepSeek Chat, AI-X Grok, and optional Claude Sonnet 3.5.
-   **Specialized AI Systems**: Includes GPT Auto Suggest, Multi-AI Consensus Scorer, Adaptive Prompt Engine, Market Intelligence Brain, Portfolio Intelligence, News Sentiment Analyzer, and Auto-Flip System.
-   **Post-Trade AI Review System**: All 5 AI brains independently analyze completed trades across entry quality, SL/TP placement, position management, and exit timing.
-   **Autonomous Improvement System**: When 3+ brains reach a 60%+ consensus, the system automatically applies parameter improvements and commits changes to GitHub, including SL/TP multipliers, minimum RR thresholds, leverage caps, quality score filters, and BE/Trailing trigger points.

### Validation & Safety Infrastructure
Includes a Validation Pipeline (backtesting), Fail-Closed Decision Gates (Dual Confirmation), Data-Driven Monte Carlo simulations, a Live Health Monitor, and Circuit Breakers.

### Telegram Digest System
Consolidated notification system with batched reports (Hotfix 2025-11-06):
-   **Health Digests**: Three daily reports (08:00, 16:00, 00:00 Israel time) on system status, worker health, and daily summaries.
-   **Trade/PnL Digests**: Sent every 30 minutes ONLY if there are significant events (SL/TP hits, closed trades, position updates). No spam!
-   **Critical Alerts**: Immediate notifications ONLY for true emergencies (system failures, circuit breaker, security breaches). Everything else queued to digest.
-   **AI Trade Reviews**: Sent immediately upon trade completion, summarizing 5-brain analysis with consensus scores and auto-applied improvements.
-   **Rate Limiting**: Maximum 3 immediate messages per 30-minute window; overflow automatically queued to next digest.

### Deployment Architecture
The production environment runs on Render.com with 8 background workers and a Neon PostgreSQL database, connected to GitHub for auto-deployment. Replit is used solely for development and testing. The system supports a 3-phase progressive rollout for dynamic regime trading, currently in full production (Phase 3).

## External Dependencies

-   **Binance Futures API**: Market data, order execution, account management (Hedge Mode enforced).
-   **Neon PostgreSQL API**: Auto-resume endpoint management to prevent database auto-pause.
-   **OpenAI API**: GPT-5 for AI trade proposals, market analysis, and post-trade reviews.
-   **Google Gemini API**: Gemini 2 Pro for fast multi-modal reasoning and trade scoring.
-   **DeepSeek API**: AI provider for trade optimization and post-trade analysis.
-   **AI-X/Grok API**: AI provider for system supervision and trade reviews.
-   **Anthropic Claude API**: Claude Sonnet 3.5 for consensus validation and post-trade scoring.
-   **GitHub API**: Auto-commit system improvements when AI consensus reached (3+ brains, 60%+ agreement).
-   **Telegram Bot API**: Notifications, approval workflows, interactive callbacks, digest reports.
-   **N8N Workflow Automation**: External workflow integration, news ingestion.
-   **Gunicorn**: Production-grade WSGI HTTP server.
-   **PostgreSQL (Neon)**: Persistent data storage with auto-resume capability.
-   **psycopg[binary]>=3.2.0**: Modern PostgreSQL adapter (replaces psycopg2).
-   **psutil**: System and process monitoring.
-   **httpx**: Async HTTP client for AI provider API calls.
-   **scipy**: Scientific computing for statistical analysis.
-   **numpy**: Numerical computing for simulations and metrics.

## Recent Changes (2025-11-06)

**MetaBrain v8.0 Hotfix #1 - Critical Fixes:**
1. ✅ **Neon Auto-Resume**: `utils/neon_resume.py` - Prevents database downtime
2. ✅ **Hedge Mode Fix**: `utils/position_mode.py` + `utils/order_params.py` - Eliminates APIError -4061
3. ✅ **TP Ladder Fix**: `utils/price_math.py` - No more negative prices, proper tick quantization
4. ✅ **Telegram Digest**: Enhanced `utils/telegram_digest.py` - Spam prevention with 30-min batching
5. ✅ **ENV Validation**: `utils/env_validate.py` - Clear logging of missing providers
6. ✅ **Main Integration**: Updated `main.py` with all hotfix modules on startup

**MetaBrain v8.0 Hotfix #2 (2025-11-06) - Telegram Spam Fix + SPOT Trading:**
1. ✅ **Auto Health Monitor Fix**: Now sends alerts to Digest Queue instead of direct Telegram (prevents 200+ daily spam messages)
2. ✅ **Position Monitor Fix**: Sends position reports to Digest Queue (batched every 30 min or at scheduled health digests)
3. ✅ **SPOT Trading Enabled**: Added `SUGGEST_SPOT=1` to `.env.example` - Auto Scanner will now scan both FUTURES + SPOT markets
4. ⚠️ **Auto Scanner Workflow**: Due to workflow management cache issues, Auto Scanner workflow needs manual update to include `SUGGEST_SPOT=1` environment variable

**Post-Trade AI Review System:**
- All 5 AI brains analyze completed trades independently
- Scores: Entry Quality, SL/TP Placement, Position Management, Exit Timing (0-100 each)
- Consensus engine identifies improvements when 3+ brains agree (60%+ threshold)
- Auto-improvement: Updates `config/trading_params.yaml`, commits to GitHub, triggers deployment
- Full implementation in `utils/ai_post_trade_review.py` + `utils/ai_consensus_improver.py`

**Files Created:**
- `utils/neon_resume.py` - Neon API integration
- `utils/position_mode.py` - Hedge Mode enforcement
- `utils/order_params.py` - Safe order building
- `utils/price_math.py` - Dynamic TP/SL calculation
- `utils/env_validate.py` - ENV validation
- `scripts/neon_resume.sh` - Manual resume script

**Files Updated:**
- `main.py` - Startup hooks for all hotfix modules
- `.env.example` - Added all new environment variables
- `requirements.txt` - Already has `psycopg[binary]>=3.2.0`

**Environment Variables Required:**
```bash
# Neon Auto-Resume (Optional but recommended)
NEON_API_KEY=
NEON_PROJECT_ID=
NEON_ENDPOINT_ID=

# Binance Hedge Mode (Default: enabled)
BINANCE_FORCE_HEDGE_MODE=1

# Telegram Digest (Default: enabled, 30-min intervals)
TELEGRAM_DIGEST_ENABLED=1
TELEGRAM_DIGEST_INTERVAL_SEC=1800
TELEGRAM_IMMEDIATE_SEVERITIES=CRITICAL

# AI Providers for Post-Trade Review
ANTHROPIC_API_KEY=  # Claude Sonnet 3.5 (1 of 5 brains)
DEEPSEEK_API_KEY=   # Optional
# OpenAI, Gemini, XAI already configured

# GitHub Auto-Commit (for AI consensus improvements)
GITHUB_TOKEN=
GITHUB_REPO=shawn2400/market-gpt-api-template
AUTO_IMPROVE_ENABLE=1
```