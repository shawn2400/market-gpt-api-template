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
Consolidated notification system with batched reports:
-   **Health Digests**: Three daily reports on system status and summaries.
-   **Trade/PnL Digests**: Sent every 30 minutes for significant events, including closed trades, PnL summaries, and active positions.
-   **Critical Alerts**: Immediate notifications for system failures, trade execution errors, and security breaches.
-   **AI Trade Reviews**: Sent upon trade completion, summarizing multi-brain analysis and improvement proposals.

### Deployment Architecture
The production environment runs on Render.com with 8 background workers and a Neon PostgreSQL database, connected to GitHub for auto-deployment. Replit is used solely for development and testing. The system supports a 3-phase progressive rollout for dynamic regime trading, currently in full production (Phase 3).

## External Dependencies

-   **Binance Futures API**: Market data, order execution, account management.
-   **OpenAI API**: GPT-5 for AI trade proposals and market analysis.
-   **Google Gemini API**: Gemini 2 Pro for fast multi-modal reasoning.
-   **DeepSeek API**: AI provider for trade optimization.
-   **AI-X/Grok API**: AI provider for system supervision.
-   **Anthropic Claude API**: Claude Sonnet 3.5 for consensus validation.
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