# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous algorithmic trading platform designed for 24/7 Binance Futures trading. It automatically scans 534 symbols, making AI-powered trade decisions through DeepSeek Chat ($0.0001/call - ultra-cheap and reliable, ~$1-2/month total cost). The platform integrates 7 trading strategies (Mean-Reversion, Scalping, Range-Bounce, Trend-Following, Breakout, GRID, SPOT) with dynamic capital management, aiming for 4-10 high-quality daily trades. Its MetaBrain v9.1 eliminates hardcoded logic, with all trade parameters determined by AI analysis. The system features intelligent brain management with auto-suspend/resume for failed providers, ready to scale to multi-brain consensus when additional providers are activated. The system operates autonomously, supported by a self-adaptive engine and complete data persistence across 8 background workers.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations.

## System Architecture

### UI/UX
The system features a dashboard UI and enhanced Telegram notifications, utilizing HTML formatting, emojis, and inline interactive buttons for improved user experience.

### Technical Implementations
The core application is built with FastAPI and Gunicorn, emphasizing modularity and policy management via YAML files.

**Core Features:**
-   **Automated Trading Modes**: Supports MARKET, HYBRID, and FULL AUTO execution.
-   **Live Trade Management**: Dynamic management of open positions with TP, SL, BE logic, and ATR-based trailing stops.
-   **Market Scanner**: Autonomous worker performs multi-timeframe technical analysis across Binance Futures markets.
-   **AI-Powered Proposals**: Utilizes DeepSeek Chat (ultra-cheap, $0.0001/call) for trade decisions with adaptive Risk/Reward thresholds and intelligent brain management. Additional brains (Qwen, Gemini, Claude, Grok) available when activated.
-   **GRID Trading**: Integrated FUTURES GRID trading.
-   **Risk Management**: Implements quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
-   **Dynamic Budget System**: Real-time trade budget calculation based on account equity, trade quality, volatility, and defined floors/ceilings.
-   **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit, adapting to market volatility.
-   **Complete Data Persistence**: All critical data is saved to a PostgreSQL database.

**MetaBrain v9.1 - 100% AI-Driven Precision Trading:**
-   **1-Brain Lean Architecture (Current)**: Uses DeepSeek Chat (ultra-cheap $0.0001/call) for 99%+ cost reduction (~$1-2/month vs $600-800 with GPT-5). Single brain makes all trade decisions with full autonomy.
-   **Intelligent Brain Management System**: Auto-suspend/resume for failed providers (429 errors, timeouts, API failures). Ready to scale to multi-brain consensus when additional providers activated. Dynamic consensus threshold adjusts automatically based on active brains. Includes cost tracking and token budgeting.
-   **Optional Expansion Brains (SUSPENDED)**: Qwen 2.5 Turbo (FREE, needs valid API key), Gemini 2 Pro ($0.00005/call, rate limited), Claude Sonnet ($0.003/call, needs credits), Grok (XAI, $0.001/call). Can be activated anytime for 2/3 or 3/3 consensus.
-   **AI Strategy Consensus Engine**: 100% AI-driven strategy selection via a 3-brain voting system based on independent market analysis.
-   **Precision Calculator v1.0**: Calculates exact leverage and investment amounts based on trade quality, market volatility, regime, and balance.
-   **Deep Market Analyzer**: Multi-layer technical analysis covering trend, volatility, support/resistance, market structure, and volume.
-   **Live Regime Detector**: Real-time market classification (TRENDING, CHOPPY, VOLATILE, SIDEWAYS) using ADX, ATR, Bollinger Bands, and price range.
-   **Entry Timing Optimizer**: Analyzes recent price action and volatility for optimal entry timing.
-   **Dynamic Protection Manager**: AI suggests regime-specific parameter sets (Entry Quality, SL ATR, TP RR, Trail ATR, Leverage) within wide safety ranges, with guardrails from `order_sanity.py`, `leverage_policy.py`, `precision_calculator.py`.
-   **Accurate ROI Calculation**: Based on PnL_USDT / actual_investment, accounting for leverage.
-   **Dual Order Types**: Uses both LIMIT and MARKET orders dynamically.
-   **Smart Position Mode Compatibility**: Adapts to Binance Hedge Mode and One-Way Mode.
-   **AI Consensus Parameters**: Final parameter values are the median of proposals from all AI brains within wide safety ranges.
-   **Database Resilience**: 3-layer protection including auto-pause prevention, exponential backoff retries, and fallback queries.

**ExecutionBot - Unified Trade Execution Wrapper:**
-   **Centralized Architecture**: All trade execution logic consolidated into single wrapper (`utils/execution_bot.py`) from 5+ entry points (API, Telegram, Ops Approval, Auto Scanner, Autopilot).
-   **Source-Aware Approval Gating**: Intelligent bypass for already-approved sources (ops_approval*, telegram*) and automation flows (auto_trade, autopilot) to prevent regression.
-   **Dual Flow Support**: MARKET flow (budget-only) and HYBRID flow (custom TP/SL) with automatic fallback on -4061 errors.
-   **Unified Logging**: Consistent format across all entry points: "[ExecutionBot] open_position source=X flow=Y symbol=Z status=W"
-   **Backward Compatible**: External API response formats preserved for external consumers.
-   **Entry Points**: `/trade/execute`, `/trade/approve`, `/telegram/webhook`, `/ops/approve`, `/auto/trade`, `/autopilot`

### AI Brains System
The system integrates a **scalable multi-brain architecture** with intelligent management:

**Active Brain (99%+ cost reduction vs GPT-5):**
1. **DeepSeek Chat** - Deep market analysis ($0.0001/call, ultra-cheap + reliable) ✅ ACTIVE

**Suspended Brains (Ready for Activation):**
2. **Qwen 2.5 Turbo** - Fast reasoning (FREE! - Alibaba Cloud DashScope) - Needs valid API key
3. **Gemini 2 Pro** - Multi-modal analysis ($0.00005/call, ultra-cheap + fast) - Rate limited, can switch models
4. **Claude Sonnet** - High-quality analysis ($0.003/call) - Needs credits top-up
5. **Grok (XAI)** - Contrarian analysis ($0.001/call) - Optional fallback

**Brain Management Features:**
- **Auto-Suspend/Resume**: Automatically suspends brains on failures (429, timeout, API errors). Auto-resumes when API recovers (checked hourly).
- **Dynamic Consensus**: Threshold adjusts automatically based on active brains (1/1 for single brain, 2/3 for multiple).
- **Cost Tracking**: Real-time monitoring of API costs and token usage per brain.
- **Scalable Architecture**: Seamlessly switches from 1-brain to multi-brain consensus when additional providers activated.
- **Token Budgeting**: Max 300 tokens/call for cost optimization.

**Current Monthly Cost:** ~$1-2/month (vs $600-800 with GPT-5 only) = **99%+ cost savings!**

The system also includes specialized AI systems for market intelligence, portfolio intelligence, news sentiment, and a **Post-Trade AI Review System**. An **Autonomous Improvement System** automatically applies parameter improvements with 60%+ consensus from 3+ brains (when multi-brain active).

### Validation & Safety Infrastructure
Includes a Validation Pipeline (backtesting), Fail-Closed Decision Gates (Dual Confirmation), Data-Driven Monte Carlo simulations, a Live Health Monitor, and Circuit Breakers.

**🛡️ Emergency Protection System (3-Layer Defense):**
-   **Layer 1 - Pre-Trade Validation**: Every trade requires SL+TP configuration before execution.
-   **Layer 2 - Post-Entry Verification**: Verifies SL/TP orders on Binance within 2 seconds. Missing orders trigger emergency close + circuit breaker.
-   **Layer 3 - Continuous Monitoring**: Checks for unprotected positions every 30 seconds. If detected, triggers immediate market close + system pause.
-   **Circuit Breaker**: Auto-triggers upon detection of 2+ unprotected positions within 1 hour, pausing auto-run and sending critical alerts.

### Telegram Digest System
Consolidated notification system with batched reports for Health, Trade/PnL, Critical Alerts, and AI Trade Reviews, with rate limiting.

### Deployment Architecture
The production environment runs on Render.com with **8 Background Workers** and a Neon PostgreSQL database, connected to GitHub for auto-deployment. Replit is used for development.

## External Dependencies

-   **Binance Futures API**: Market data, order execution, account management.
-   **Neon PostgreSQL API**: Auto-resume endpoint management.
-   **OpenAI API**: GPT-5 for AI trade proposals, market analysis, post-trade reviews.
-   **Google Gemini API**: Gemini 2 Pro for fast multi-modal reasoning and trade scoring.
-   **DeepSeek API**: Ultra-cheap AI provider for trade optimization and consensus voting.
-   **Alibaba Cloud DashScope API**: Qwen 2.5 Turbo (FREE) for fast AI reasoning and consensus.
-   **AI-X/Grok API**: Optional fallback AI provider (suspended by default, auto-resumes when credits available).
-   **Anthropic Claude API**: Claude Sonnet 3.5 for consensus validation and post-trade scoring.
-   **GitHub API**: Auto-commit system improvements.
-   **Telegram Bot API**: Notifications, approval workflows, interactive callbacks, digest reports.
-   **N8N Workflow Automation**: External workflow integration, news ingestion.
-   **Gunicorn**: Production-grade WSGI HTTP server.
-   **PostgreSQL (Neon)**: Persistent data storage.