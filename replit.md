# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an algorithmic trading platform for 24/7 live Binance Futures trading. It automates market scanning across 534 symbols, utilizes 100% autonomous AI-powered trade decisions via **5 AI Brains** consensus engine (GPT-5, Gemini 2 Pro, DeepSeek, Grok, Claude), and integrates **7 Trading Strategies** (Mean-Reversion, Scalping, Range-Bounce, Trend-Following, Breakout, GRID, SPOT) with dynamic capital management. The platform features a self-adaptive trading engine with complete data persistence via **8 Background Workers**, aiming for 4-10 high-quality daily trades, profitability, and autonomous operation. **MetaBrain v9.0** introduces fully autonomous, fully dynamic trading with hierarchical AI consensus, regime-driven dynamic parameters, and 100% strategic freedom across all market conditions.

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
-   **5-Brain Hierarchical Consensus Architecture**: 
    - **GPT-5** (gpt-5-2025-08-07) - Lead Orchestrator ✅
    - **Gemini 2 Pro** (gemini-2.0-flash-exp) - Fast Multi-Modal Analyst ⚠️ (50/day quota)
    - **DeepSeek** (deepseek-chat) - Deep Pattern Analyst ✅
    - **Grok** (grok-2-latest) - Contrarian Analyst ✅
    - **Claude Sonnet 3.5** (claude-3-5-sonnet-20241022) - Conservative Risk Validator ✅
    - **Consensus Rule**: ≥3 APPROVE required out of 5 to execute trade
-   **Dynamic Protection Manager**: Maintains 4 regime-specific parameter sets with AI consensus (Entry Quality, SL ATR, TP RR, BE Trigger, Trail ATR, Leverage)
    - TRENDING: Entry Quality ≥5.8, SL ATR×1.7, TP RR 2.0, BE +0.4%, Trail ATR×0.9, Lev 6x
    - CHOPPY: Entry Quality ≥6.5, SL ATR×1.3, TP RR 1.4, BE +0.6%, Trail ATR×0.6, Lev 3x
    - VOLATILE: Entry Quality ≥6.2, SL ATR×1.9, TP RR 2.2, BE +0.5%, Trail ATR×1.0, Lev 4x
    - SIDEWAYS: Entry Quality ≥6.0, SL ATR×1.4, TP RR 1.3, BE +0.6%, Trail ATR×0.7, Lev 5x
-   **Regime-Based Quality Thresholds**: Quality requirements adapt to market regime (5.8-6.5) instead of static 8.5, enabling realistic trade generation
-   **Regime Detector**: Automatically detects market regime using ADX, ATR, Bollinger Bands, and price range analysis
-   **Dual Order Types**: System uses BOTH LIMIT (precision entry) and MARKET (instant execution) orders dynamically based on regime and volatility
-   **100% Strategic Freedom**: Generates trades in EVERY market condition (LONG/SHORT/GRID/SPOT/Scalping/Mean-Reversion)
-   **AI Consensus Parameters**: Each brain proposes parameters within base protection ranges; final values = median of all brains
-   **Database Resilience**: 3-layer protection including auto-pause prevention, exponential backoff retries, fallback to query without 'paused' column for legacy database compatibility
-   **Daily Trading Reports**: Comprehensive Telegram reports with PnL, Win Rate, and trade summaries (70% Hebrew, 30% English)
-   **Security & Authentication**: Uses Bearer Token (`X-API-Key`) and HMAC Signature, with anti-replay protection
-   **Alert Management**: Auto Health Monitor uses 5 consecutive failures + 15-minute cooldown before sending CRITICAL alerts, preventing spam from intermittent database issues

### AI Brains System (5 Active Brains)
The system integrates **5 AI brains** in a hierarchical consensus architecture:
-   **Multi-AI Consensus Engine**: Orchestrated by OpenAI GPT-5 (gpt-5-2025-08-07), supported by Google Gemini 2 Pro (gemini-2.0-flash-exp), DeepSeek Chat (deepseek-chat), AI-X Grok (grok-2-latest), and Anthropic Claude Sonnet 3.5 (claude-3-5-sonnet-20241022).
-   **Specialized AI Systems**: Includes GPT Auto Suggest, Multi-AI Consensus Scorer, Adaptive Prompt Engine, Market Intelligence Brain, Portfolio Intelligence, News Sentiment Analyzer, and Auto-Flip System.
-   **Post-Trade AI Review System**: All 5 AI brains independently analyze completed trades across entry quality, SL/TP placement, position management, and exit timing.
-   **Autonomous Improvement System**: When 3+ brains reach a 60%+ consensus, the system automatically applies parameter improvements and commits changes to GitHub, including SL/TP multipliers, minimum RR thresholds, leverage caps, quality score filters, and BE/Trailing trigger points.
-   **Order Cleanup on Trade Close**: Position Monitor automatically cancels all remaining TP/SL/Trailing orders when a position is closed (prevents orphaned orders).

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
The production environment runs on Render.com with **8 Background Workers** and a Neon PostgreSQL database, connected to GitHub for auto-deployment. Replit is used for development and testing. The system supports a 3-phase progressive rollout for dynamic regime trading, currently in full production (Phase 3).

**8 Workers:**
1. AlgoGPT Server (FastAPI + Gunicorn)
2. Auto Health Monitor (30s health checks)
3. Auto Scanner (120s market scans)
4. Daily Meeting 00:00 (daily reports)
5. Fills Watcher (15s order tracking)
6. GPT-5 Central Brain (orchestration)
7. Position Monitor (30min PnL reports + order cleanup)
8. Sentinel Security (anomaly detection)

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