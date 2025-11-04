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

**Core Features:**
-   **Automated Trading Modes**: Supports MARKET, HYBRID, and AUTO execution.
-   **Live Trade Management**: Dynamic management of open positions with TP, SL, BE logic, and ATR-based trailing stops.
-   **Market Scanner**: Autonomous worker performs multi-timeframe technical analysis every 60 seconds across 531 Binance Futures markets.
-   **AI-Powered Proposals**: OpenAI GPT-5 generates trade proposals with mandatory Risk/Reward (RR) ≥ 1.3. Multi-AI consensus is available via DeepSeek and AI-X/Grok.
-   **GRID Trading**: Integrated FUTURES GRID trading for choppy/sideways markets.
-   **Risk Management**: Implements quality filters, dynamic filters, liquidity checks, cooldown periods, daily trade caps, and a circuit breaker for daily loss limits.
-   **Telegram Approval Workflow**: Interactive approval for trade proposals.
-   **Dynamic Position Management**: Features ATR Trailing, Multi-level TP ladder, and Dynamic Position Sizing.
-   **Auto-Flip**: Dynamically adapts to market conditions, proposing LONG or SHORT trades with multi-system validation.
-   **Self-Adaptive Trading Engine**: Incorporates Market Intelligence (regime, mood, volatility detection), Adaptive AI Prompts, and Portfolio Intelligence (exposure management, correlation prevention).
-   **Dynamic Capital Optimization**: Automatically calculates leverage and position sizing based on trade quality, RR, AI confidence, and market conditions.
-   **Complete Data Persistence**: All critical data, including trade sizing, market states, and performance records, is saved to a PostgreSQL database.

**Security & Authentication:**
-   Uses Bearer Token (`X-API-Key`) and HMAC Signature.
-   Includes anti-replay protection and mandatory Telegram approval.

### AI Brains System
AlgoGPT integrates 8+ specialized AI systems:
-   **GPT-5 Central Brain**: Master AI orchestrator for high-level analysis and coordination.
-   **GPT Auto Suggest**: Autonomous market scanner for multi-timeframe analysis and trade proposals.
-   **Multi-AI Consensus Scorer**: Combines GPT-5, DeepSeek, and AI-X (Grok) for trade quality scoring.
-   **DeepSeek Optimizer**: Specializes in parameter optimization for entry points, TP/SL, and position sizing.
-   **AI-X (Grok) Supervisor**: Monitors system health and detects anomalies.
-   **Adaptive Prompt Engine**: Generates dynamic AI prompts based on market regime.
-   **Market Intelligence Brain**: Detects market regime, volatility, and mood.
-   **Portfolio Intelligence**: Manages exposure, position limits, and correlation.
-   **News Sentiment Analyzer**: Analyzes crypto news headlines for market sentiment.
-   **Auto-Flip System**: Makes directional decisions (LONG/SHORT) based on multi-timeframe analysis.

### Validation & Safety Infrastructure (v2.0)
Includes a **Validation Pipeline** (historical backtesting with walk-forward testing), **Fail-Closed Decision Gates** (Dual Confirmation: Quant ∧ AI ∧ Risk), **Data-Driven Monte Carlo** simulations, a **Live Health Monitor**, and **Circuit Breakers** (daily drawdown, consecutive loss limits).

### Production Enhancements (Phase 1)
All 38 tasks completed, including AI performance tracking (dynamic model weighting, prediction logging, outcome tracking, feedback dataset for fine-tuning, AI leaderboard), database hardening (10 tables for slippage, circuit breaker state, market states, audit logs, AI predictions, etc.), and enhanced monitoring & security (real-time P&L, tiered alerting, rate limiting, log masking, audit trail, IP throttling, comprehensive testing).

### Deployment Architecture
The system is designed for **production deployment on Render.com** with full infrastructure-as-code configuration:
-   **render.yaml**: Defines all 7 services (1 web + 6 background workers) + PostgreSQL database
-   **Render.com Production**: Managed PostgreSQL, 2GB RAM web service, dedicated background workers
-   **Estimated Cost**: ~$74/mo ($25 web service + $7 database + $42 for 6 workers)
-   **Deployment Script**: `scripts/deploy_to_render.py` automates service creation via Render API
-   **Domain**: Primary production domain on Render.com (e.g., `algogpt-server.onrender.com`)
-   **Development Environment**: Can be developed/tested on Replit, deployed to Render for production

## External Dependencies

-   **Binance Futures API**: Market data, order execution, account management.
-   **OpenAI API**: GPT-5 (gpt-5-2025-08-07) for AI trade proposals and market analysis.
-   **DeepSeek API**: AI provider for trade optimization and multi-AI consensus.
-   **AI-X/Grok API**: AI provider for system supervision and consensus.
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