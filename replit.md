# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an algorithmic trading platform for 24/7 live Binance Futures trading. It automates market scanning across 534 symbols, utilizes 100% autonomous AI-powered trade decisions via 7-Brain architecture (2 AI Scouts + 5 AI Decision Makers), and integrates GRID trading with dynamic capital management. The platform features a self-adaptive trading engine with complete data persistence, aiming for 4-10 high-quality daily trades, profitability, and autonomous operation. **MetaBrain v9.0** introduces fully autonomous, fully dynamic trading with hierarchical AI consensus, regime-driven dynamic parameters, and 100% strategic freedom (LONG/SHORT/GRID/SPOT/Scalping/Mean-Reversion) across all market conditions.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations.

## System Architecture

### UI/UX
The system provides a dashboard UI and enhanced Telegram notifications, utilizing HTML formatting, emojis, and inline interactive buttons for improved user experience.

### Technical Implementations
The core application is built with FastAPI and Gunicorn, featuring modularized functionalities and policy management via YAML files.

**Core Features:**
-   **Automated Trading Modes**: Supports MARKET, HYBRID, and FULL AUTO execution.
-   **Live Trade Management**: Dynamic management of open positions with TP, SL, BE logic, and ATR-based trailing stops.
-   **Market Scanner**: Autonomous worker performs multi-timeframe technical analysis across 531 Binance Futures markets.
-   **AI-Powered Proposals**: Utilizes 5 AI providers (GPT-5, Gemini 2 Pro, DeepSeek, Grok, Claude) for consensus-based trade decisions with adaptive Risk/Reward thresholds.
-   **GRID Trading**: Integrated FUTURES GRID trading.
-   **Mean-Reversion Strategy**: Deterministic VWAP-based strategy.
-   **Scalping & Range-Bounce Strategies**: Aggressive short-term strategies.
-   **Risk Management**: Implements quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
-   **Dynamic Budget System**: Real-time trade budget calculation based on account equity, trade quality, volatility, and defined floors/ceilings.
-   **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit, adapting to market volatility.
-   **Complete Data Persistence**: All critical data is saved to a PostgreSQL database.

**MetaBrain v9.0 - 100% Autonomous Dynamic Trading:**
-   **7-Brain Hierarchical Architecture**: 
    - **2 AI Scouts**: Market Scanner (identifies opportunities across 534 symbols) + Technical Analyst (deep technical analysis)
    - **5 AI Decision Makers**: GPT-5, Gemini 2 Pro, DeepSeek, Grok, Claude Sonnet 3.5 vote independently (≥3 APPROVE required)
-   **Dynamic Protection Manager**: Maintains 4 regime-specific parameter sets (Entry Quality, SL ATR, TP RR, BE Trigger, Trail ATR, Leverage)
    - TRENDING: Entry 5.8, SL ATR×1.7, TP RR 2.0, BE +0.4%, Trail ATR×0.9, Lev 6x
    - CHOPPY: Entry 6.5, SL ATR×1.3, TP RR 1.4, BE +0.6%, Trail ATR×0.6, Lev 3x
    - VOLATILE: Entry 6.2, SL ATR×1.9, TP RR 2.2, BE +0.5%, Trail ATR×1.0, Lev 4x
    - SIDEWAYS: Entry 6.0, SL ATR×1.4, TP RR 1.3, BE +0.6%, Trail ATR×0.7, Lev 5x
-   **Regime Detector**: Automatically detects market regime using ADX, ATR, Bollinger Bands, and price range analysis
-   **Dual Order Types**: System uses BOTH LIMIT (precision entry) and MARKET (instant execution) orders dynamically based on regime and volatility
-   **100% Strategic Freedom**: Generates trades in EVERY market condition (LONG/SHORT/GRID/SPOT/Scalping/Mean-Reversion)
-   **AI Consensus Parameters**: Each brain proposes parameters within base protection ranges; final values = median of all brains
-   **Database Resilience**: 3-layer protection including auto-pause prevention, exponential backoff retries, and fallback queue to JSON
-   **Daily Trading Reports**: Comprehensive Telegram reports with PnL, Win Rate, and trade summaries (70% Hebrew, 30% English)
-   **Security & Authentication**: Uses Bearer Token (`X-API-Key`) and HMAC Signature, with anti-replay protection

### AI Brains System
The system integrates 9+ specialized AI systems with 5 AI providers for consensus-based decisions:
-   **Multi-AI Consensus Engine**: Orchestrated by OpenAI GPT-5, supported by Google Gemini 2 Pro, DeepSeek Chat, AI-X Grok, and optional Claude Sonnet 3.5.
-   **Specialized AI Systems**: Includes GPT Auto Suggest, Multi-AI Consensus Scorer, Adaptive Prompt Engine, Market Intelligence Brain, Portfolio Intelligence, News Sentiment Analyzer, and Auto-Flip System.
-   **Post-Trade AI Review System**: All 5 AI brains independently analyze completed trades across entry quality, SL/TP placement, position management, and exit timing.
-   **Autonomous Improvement System**: When 3+ brains reach a 60%+ consensus, the system automatically applies parameter improvements and commits changes to GitHub, including SL/TP multipliers, minimum RR thresholds, leverage caps, quality score filters, and BE/Trailing trigger points.

### Validation & Safety Infrastructure
Includes a Validation Pipeline (backtesting), Fail-Closed Decision Gates (Dual Confirmation), Data-Driven Monte Carlo simulations, a Live Health Monitor, and Circuit Breakers.

### Telegram Digest System
Consolidated notification system with batched reports:
-   **Health Digests**: Three daily reports on system status and worker health.
-   **Trade/PnL Digests**: Sent every 30 minutes if significant events occur.
-   **Critical Alerts**: Immediate notifications only for true emergencies.
-   **AI Trade Reviews**: Sent immediately upon trade completion.
-   **Rate Limiting**: Maximum 3 immediate messages per 30-minute window; overflow queued to next digest.

### Deployment Architecture
The production environment runs on Render.com with 8 background workers and a Neon PostgreSQL database, connected to GitHub for auto-deployment. Replit is used for development and testing. The system supports a 3-phase progressive rollout for dynamic regime trading, currently in full production (Phase 3).

## External Dependencies

-   **Binance Futures API**: Market data, order execution, account management (Hedge Mode enforced).
-   **Neon PostgreSQL API**: Auto-resume endpoint management.
-   **OpenAI API**: GPT-5 for AI trade proposals, market analysis, and post-trade reviews.
-   **Google Gemini API**: Gemini 2 Pro for fast multi-modal reasoning and trade scoring.
-   **DeepSeek API**: AI provider for trade optimization and post-trade analysis.
-   **AI-X/Grok API**: AI provider for system supervision and trade reviews.
-   **Anthropic Claude API**: Claude Sonnet 3.5 for consensus validation and post-trade scoring.
-   **GitHub API**: Auto-commit system improvements.
-   **Telegram Bot API**: Notifications, approval workflows, interactive callbacks, digest reports.
-   **N8N Workflow Automation**: External workflow integration, news ingestion.
-   **Gunicorn**: Production-grade WSGI HTTP server.
-   **PostgreSQL (Neon)**: Persistent data storage.
-   **psycopg[binary]>=3.2.0**: PostgreSQL adapter.
-   **psutil**: System and process monitoring.
-   **httpx**: Async HTTP client.
-   **scipy**: Scientific computing.
-   **numpy**: Numerical computing.