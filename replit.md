# AlgoGPT - Algorithmic Trading Platform (MetaBrain v8.0)

## Overview
AlgoGPT is an algorithmic trading platform for 24/7 live Binance Futures trading, built with FastAPI and Python. It automates market scanning across 530+ symbols, utilizes AI-powered trade decisions via GPT-5 and multi-AI consensus, and includes GRID trading options and dynamic capital management. The platform aims for 4-10 high-quality daily trades, focusing on profitability, minimal losses, and a self-adaptive trading engine with complete data persistence.

**MetaBrain v8.0** introduces fully autonomous regime-driven trading with 3-layer database resilience for production stability on Render.com.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations.

## System Architecture

### UI/UX
The system includes a dashboard UI (`static/dashboard/`) and enhanced Telegram notifications with HTML formatting, emojis, and inline interactive buttons for improved user experience.

### Technical Implementations
The core application uses FastAPI and Gunicorn, with modularized functionalities in `routes/` for API endpoints and `utils/` for common functions. Policies are managed via YAML files.

**Core Features:**
-   **Automated Trading Modes**: Supports MARKET, HYBRID, and FULL AUTO execution.
-   **Live Trade Management**: Dynamic management of open positions with TP, SL, BE logic, and ATR-based trailing stops.
-   **Market Scanner**: Autonomous worker performs multi-timeframe technical analysis across 531 Binance Futures markets.
-   **AI-Powered Proposals**: Utilizes 5 AI providers (GPT-5, Gemini 2 Pro, DeepSeek, Grok, Claude) for consensus-based trade decisions with adaptive Risk/Reward thresholds based on market regime.
-   **GRID Trading**: Integrated FUTURES GRID trading for choppy/sideways markets.
-   **Mean-Reversion Strategy**: Deterministic VWAP-based strategy for choppy/neutral markets using real Binance OHLCV data.
-   **Scalping & Range-Bounce Strategies**: Aggressive short-term strategies for choppy markets.
-   **Risk Management**: Implements quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
-   **Dynamic Budget System**: Trade budgets are calculated in real-time based on account equity, trade quality, volatility, and defined floors/ceilings.
-   **Dynamic SL/TP Calculation**: Stop Loss is ATR-based, and Take Profit is RR-based, adapting to market volatility and regime.
-   **Complete Data Persistence**: All critical data is saved to a PostgreSQL database.

**MetaBrain v8.0 Features:**
-   **Database Resilience (3-Layer Protection)**: 
    - Auto-pause prevention in Neon Console
    - Exponential backoff retries with wake-up handling
    - Fallback queue to JSON when DB offline + periodic resync
-   **Dynamic Regime System**: 
    - 4 market regimes: TRENDING, CHOPPY, VOLATILE, SIDEWAYS
    - Context-adaptive strategy switching (Breakout for trends, Grid for chop, Mean-reversion for sideways)
    - Regime-specific SL/TP multipliers and trailing logic
-   **Zero-Gap SL Manager**: Place new SL → Verify → Cancel old SL (never leaves position unprotected)
-   **TP Ladder System**: Multi-level take profits (TP1-TP4) with configurable weights (50%/30%/20%)
-   **Daily Trading Reports**: Comprehensive Telegram reports with PnL, Win Rate, Best/Worst trades

**Security & Authentication:**
-   Uses Bearer Token (`X-API-Key`) and HMAC Signature, with anti-replay protection and mandatory Telegram approval.

### AI Brains System (MetaBrain v7.5)
The system integrates 9+ specialized AI systems with 5 AI providers for consensus-based decisions:
-   **Multi-AI Consensus Engine**: OpenAI GPT-5 (orchestrator), Google Gemini 2 Pro (fast reasoning), DeepSeek Chat (parameter optimization), AI-X Grok (health monitoring), and Claude Sonnet 3.5 (optional validation).
-   **Specialized AI Systems**: GPT Auto Suggest, Multi-AI Consensus Scorer, Adaptive Prompt Engine, Market Intelligence Brain, Portfolio Intelligence, News Sentiment Analyzer, and Auto-Flip System.

### Validation & Safety Infrastructure (v2.0)
Includes a Validation Pipeline (backtesting), Fail-Closed Decision Gates (Dual Confirmation), Data-Driven Monte Carlo simulations, a Live Health Monitor, and Circuit Breakers.

### Deployment Architecture
The production environment runs on Render.com with 8 background workers and a Neon PostgreSQL database (ep-cool-tooth-a5dlnc71), connected to GitHub for auto-deployment. Replit is used solely for development and testing, with a separate development database. The system is platform-agnostic and does not rely on Replit-specific features for production.

**MetaBrain v8.0 Production Requirements:**
- Neon Database: Auto-pause DISABLED in console (prevents trade failures)
- Database Resilience: 3-layer protection enabled (backoff retries + fallback queue)
- Dynamic Regime System: FORCE_REGIME="" (auto-detection enabled)
- Capital: $166 USDT for 5-6 simultaneous positions
- Dependencies: psycopg[binary]>=3.2.1 for PostgreSQL 3.x support

## External Dependencies

-   **Binance Futures API**: Market data, order execution, account management.
-   **OpenAI API**: GPT-5 for AI trade proposals and market analysis.
-   **Google Gemini API**: Gemini 2 Pro for fast multi-modal reasoning.
-   **DeepSeek API**: AI provider for trade optimization.
-   **AI-X/Grok API**: AI provider for system supervision.
-   **Anthropic Claude API** (optional): Claude Sonnet 3.5 for consensus validation.
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