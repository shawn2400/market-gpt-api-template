# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous algorithmic trading platform designed for 24/7 Binance Futures trading. It automatically scans 534 symbols, making AI-powered trade decisions through a consensus engine of 5 advanced AI models (GPT-5, Gemini 2 Pro, DeepSeek, Grok, Claude). The platform integrates 7 trading strategies (Mean-Reversion, Scalping, Range-Bounce, Trend-Following, Breakout, GRID, SPOT) with dynamic capital management, aiming for 4-10 high-quality daily trades. Its MetaBrain v9.1 eliminates hardcoded logic, with all trade parameters determined by hierarchical AI consensus. The system operates autonomously, supported by a self-adaptive engine and complete data persistence across 8 background workers.

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
-   **AI-Powered Proposals**: Utilizes 5 AI providers for consensus-based trade decisions with adaptive Risk/Reward thresholds.
-   **GRID Trading**: Integrated FUTURES GRID trading.
-   **Risk Management**: Implements quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
-   **Dynamic Budget System**: Real-time trade budget calculation based on account equity, trade quality, volatility, and defined floors/ceilings.
-   **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit, adapting to market volatility.
-   **Complete Data Persistence**: All critical data is saved to a PostgreSQL database.

**MetaBrain v9.1 - 100% AI-Driven Precision Trading:**
-   **5-Brain Hierarchical Consensus Architecture**: Orchestrated by GPT-5, supported by Gemini 2 Pro, DeepSeek, Grok, and Claude Sonnet 3.5. Requires ≥3 brains to approve for trade execution.
-   **AI Strategy Consensus Engine**: 100% AI-driven strategy selection via a 5-brain voting system based on independent market analysis.
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

### AI Brains System
Integrates **5 AI brains** in a hierarchical consensus architecture: OpenAI GPT-5 (orchestrator), Google Gemini 2 Pro, DeepSeek Chat, AI-X Grok, and Anthropic Claude Sonnet 3.5. Includes specialized AI systems for market intelligence, portfolio intelligence, news sentiment, auto-flip, and a **Post-Trade AI Review System**. An **Autonomous Improvement System** automatically applies parameter improvements with 60%+ consensus from 3+ brains.

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
-   **DeepSeek API**: AI provider for trade optimization and post-trade analysis.
-   **AI-X/Grok API**: AI provider for system supervision and trade reviews.
-   **Anthropic Claude API**: Claude Sonnet 3.5 for consensus validation and post-trade scoring.
-   **GitHub API**: Auto-commit system improvements.
-   **Telegram Bot API**: Notifications, approval workflows, interactive callbacks, digest reports.
-   **N8N Workflow Automation**: External workflow integration, news ingestion.
-   **Gunicorn**: Production-grade WSGI HTTP server.
-   **PostgreSQL (Neon)**: Persistent data storage.