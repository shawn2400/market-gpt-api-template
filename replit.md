# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous algorithmic trading platform designed for 24/7 Binance Futures trading. It leverages AI, specifically DeepSeek Chat, to scan 534 symbols and make intelligent trade decisions. The platform integrates 7 trading strategies, dynamic capital management, and aims for 4-10 high-quality daily trades. Its MetaBrain v9.1 eliminates hardcoded logic, with all trade parameters determined by AI analysis. The system features intelligent brain management with auto-suspend/resume for failed providers and is built for scalability and autonomous operation with a self-adaptive engine and complete data persistence.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations.

## System Architecture

### UI/UX
The system provides a dashboard UI and enhanced Telegram notifications, utilizing HTML formatting, emojis, and inline interactive buttons for user interaction.

### Technical Implementations
The core application is built with FastAPI and Gunicorn, emphasizing modularity and policy management via YAML files.

**Core Features:**
-   **Automated Trading Modes**: Supports MARKET, HYBRID, and FULL AUTO execution.
-   **Live Trade Management**: Dynamic management of open positions with TP, SL, BE logic, and ATR-based trailing stops.
-   **Market Scanner**: Autonomous multi-timeframe technical analysis across Binance Futures.
-   **AI-Powered Proposals**: Uses DeepSeek Chat for trade decisions with adaptive Risk/Reward, intelligent brain management, and dynamic quality threshold enforcement. Quality scores (6-10 range) are calculated in real-time from Market Intelligence multi-factor analysis (momentum, volatility, liquidity, technical patterns).
-   **GRID Trading**: Integrated FUTURES GRID trading with dynamic symbol selection, tiered strategies, dynamic sizing engine ($25-150 budget before leverage, 1-35x leverage), and automatic SL/TP protection for all GRID fills via Fills Watcher.
-   **Risk Management**: Includes quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
-   **Dynamic Budget System v2.0**: Real-time trade budget calculation ($25-$150 per trade) based on available wallet balance, trade quality, and volatility.
-   **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit.
-   **Complete Data Persistence**: All critical data is saved to a PostgreSQL database.

**MetaBrain v9.1 - AI-Driven Precision Trading:**
-   **1-Brain Lean Architecture**: DeepSeek Chat for autonomous trade decisions, with optional expansion brains for multi-brain consensus.
-   **Intelligent Brain Management**: Auto-suspends/resumes failed AI providers, dynamic consensus thresholds, cost tracking, and token budgeting.
-   **Precision Calculator v1.0**: Calculates exact leverage and investment based on trade quality, market volatility, regime, and balance.
-   **Deep Market Analyzer & Live Regime Detector**: Multi-layer technical analysis and real-time market classification.
-   **Dynamic Protection Manager**: AI suggests regime-specific parameter sets with guardrails.
-   **Balance-Tiered Risk Profiles**: Auto-adjusts trading parameters (position size, leverage, max positions, daily risk limit) based on 5 account tiers: MICRO (<$500), CONSERVATIVE ($500-1K), BALANCED ($1K-5K), GROWTH ($5K-10K), AGGRESSIVE ($10K+). Dynamic scaling as balance grows/shrinks.
-   **Auto-Strategy Selection Engine**: Automatically chooses optimal strategy (GRID, Mean Reversion, Dip Buying, Breakout, Trend Following) based on price proximity to support/resistance levels, market regime, ADX, RSI, and volatility.
-   **Multi-Target TP System v2.0 (100% Dynamic)**: 3-level take profit with FULLY DYNAMIC exit percentages that adapt to market conditions. Exit allocations automatically adjust based on volatility, regime, strategy type, and win rate history. Front-loaded profiles (40/35/25) for high volatility/bear markets, back-loaded profiles (25/35/40) for low volatility/bull markets, balanced (30/40/30) for neutral conditions. Volatility-adjusted RR ratios, regime-aware placement, trailing stop activation at TP1 (2-5% trail). Performance monitoring system tracks effectiveness across all profiles.

**ExecutionBot - Unified Trade Execution Wrapper:**
-   Centralized architecture for all trade execution logic.
-   Source-aware approval gating and dual flow support (MARKET and HYBRID).
-   **100% SL/TP Protection**: ALL positions receive automatic Stop Loss and Take Profit orders immediately after entry. If SL/TP placement fails, position is emergency-closed automatically.

**Auto-Optimization System (Self-Adaptive Trading):**
-   **Intelligent Parameter Tuning**: Analyzes performance and adjusts `min_quality`, RR, and leverage based on win rate.
-   **Multi-Level Protection**: Activates Warning/Conservative/Emergency modes based on performance.
-   **Symbol Tiering Engine & Dynamic Blacklist Manager**: Classifies symbols by performance and auto-blacklists underperforming ones.

**Trailing TP System:**
-   Auto-activates at 25-30% profit and dynamically adjusts trailing distance to secure profits.

**Insurance Monitor System (Account Protection):**
-   Multi-layered protection including Drawdown Protection, Margin Ratio Defense, Cross/Isolated Balancer, and a Circuit Breaker.

**Validation & Safety Infrastructure:**
-   Includes a Validation Pipeline, Fail-Closed Decision Gates, Monte Carlo simulations, Live Health Monitor, and a 3-Layer Emergency Protection System.
-   Advanced Risk Manager with dynamic ATR-based SL and breakeven acceleration.
-   Entry Timestamps Persistence: Redis for primary storage with PostgreSQL backup.

**Smart LIMIT+MARKET Order Router:**
-   Decision matrix based on ATR%, spread, signal age, urgency, book depth, and breakout detection to route orders intelligently. Supports LIMIT, MARKET, and HYBRID modes.

**Order Consolidation System:**
-   Limits orders per symbol, auto-merges similar prices, and optimizes strategic TP levels with minimum distance enforcement.

**Hybrid Dynamic Leverage System v2.0:**
-   100% dynamic leverage (2-35x) adapting in real-time based on market conditions, trade quality, and multi-factor confidence scoring.
-   Includes 3-Layer Safety Guards, Market Regime Detection, Symbol Tier System, Recovery Mode, Portfolio Protection, Dynamic Position Sizing, and Time-Based Protection.

**Trading Policy Filters (System-Wide Protection):**
-   **Symbol Filter Engine**: Validates symbols based on volume, liquidity, Binance whitelist, and blacklist management.
-   **Order Quality Monitor**: Tracks fill rate, slippage, and execution speed.
-   **Position Limits Manager**: Sets max positions per symbol, total open orders, and correlation exposure limits.
-   **Trading Gatekeeper**: Unified pre-trade validation integrating all filters and Dynamic Leverage.
-   **Zero Tolerance Filter**: Auto-cleanup for expired temp blacklist entries; requires 5 failures before 24h ban.

**Dynamic TOP 50 Symbol Filter (Musical Chairs System):**
-   Blocks trades for symbols outside the TOP 50.
-   Dynamic scheduler for continuous ranking based on volume, liquidity, and volatility/performance.
-   SmartTop50Scanner for efficient candidate scanning.
-   DynamicGridApprover and TieredGridSystem for GRID trading.
-   GarbageDetector for identifying and blacklisting underperforming symbols.
-   Hybrid persistence with Redis and PostgreSQL.

### Telegram Digest System
Consolidated notification system for batched reports on Health, Trade/PnL, Critical Alerts, and AI Trade Reviews.

### Deployment Architecture
The production environment runs on Render.com with 11 Background Workers and a Neon PostgreSQL database, connected to GitHub for auto-deployment. Replit is used for development.

## External Dependencies

-   **Binance Futures API**: Market data, order execution, account management.
-   **Neon PostgreSQL**: Persistent data storage.
-   **DeepSeek API**: AI provider for trade optimization and consensus voting.
-   **Alibaba Cloud DashScope API**: Qwen 2.5 Turbo (optional AI).
-   **Google Gemini API**: Gemini 2 Pro (optional AI).
-   **Anthropic Claude API**: Claude Sonnet 3.5 (optional AI).
-   **AI-X/Grok API**: Optional fallback AI provider.
-   **Telegram Bot API**: Notifications, approval workflows, interactive callbacks.
-   **N8N Workflow Automation**: External workflow integration, news ingestion.
-   **Gunicorn**: Production-grade WSGI HTTP server.
-   **Redis Cloud**: High-performance caching and temporary data storage.