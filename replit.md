# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous AI-driven algorithmic trading platform designed for 24/7 operation on Binance Futures. It analyzes 534 symbols, executing intelligent trades based on 7 integrated strategies and dynamic capital management. The platform features an AI-driven MetaBrain that determines all trade parameters, aiming for 4-10 high-quality daily trades. It prioritizes scalability, autonomous operation through a self-adaptive engine, and complete data persistence, optimized for diverse market conditions. The business vision is to provide a robust, self-optimizing algorithmic trading solution with high market potential due to its autonomous and AI-driven adaptability.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations. All communication in Hebrew. Automatic trading with 100% dynamic automation - no time-based patterns. SL/TP fully dynamic. Budget scales with wallet size automatically.

## Recent Changes (v10.1 - Market Bias Fix)
- **Fixed Market Directional Bias**: Corrected technical fallback to use EMA alignment as tie-breaker (instead of always choosing LONG default)
- **Strengthened BTC Hard Gate**: Reduced rejection threshold from 0.5 to 0 (any positive penalty now blocks conflicting positions)
- **Issue**: System was generating excessive SHORT trades when BTC was bullish, causing -1.0 correlation penalties and portfolio losses
- **Solution**: Enhanced directional intelligence in technical fallback + stricter BTC correlation gating

## System Architecture

### UI/UX
The system provides a dashboard UI and enhanced Telegram notifications, utilizing HTML formatting, emojis, and inline interactive buttons for user interaction.

### Technical Implementations
The core application is built with FastAPI and Gunicorn, emphasizing modularity and policy management via YAML files. All critical data is saved to a PostgreSQL database.

**Core Features:**
- **Automated Trading Modes**: Supports MARKET, HYBRID, and FULL AUTO execution.
- **Live Trade Management**: Dynamic management of open positions with TP, SL, BE logic, ATR-based trailing stops, and auto-flip position reversal.
- **Market Scanner**: Autonomous multi-timeframe technical analysis across Binance Futures with weighted trend detection.
- **AI-Powered Proposals**: Uses DeepSeek Chat for trade decisions with adaptive Risk/Reward, intelligent brain management, and dynamic quality threshold enforcement.
- **Technical-Only Trading (NEW v9.4.1)**: Pure technical analysis fallback system - generates trade proposals without ANY AI dependency. Automatic activation when AI providers unavailable (402, 429, timeout). Includes Technical Strategy Selector (ADX/RSI/Volatility based) and Technical Trade Generator (ATR-based SL/TP). System works 24/7 even if all AI providers fail.
- **Resilient Trade Generation**: Two-tier proposal system: Primary (AI-driven) → Fallback (Technical-only). No single point of failure. System automatically switches between modes with zero downtime.
- **GRID Trading**: Integrated FUTURES GRID trading with dynamic symbol selection, tiered strategies, dynamic sizing, and automatic SL/TP protection.
- **Risk Management**: Includes quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
- **Dynamic Budget System**: 100% dynamic trade budget calculation based on equity-tied ceiling, quality multiplier, volatility adjustment, and floor/cap. Auto-detects wallet balance and dynamically scales all trading parameters based on balance tiers.
- **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit with multi-target TP.
- **MetaBrain - AI-Driven Precision Trading**: Features a 3-stage auto-deployment engine, 1-Brain Lean Architecture (DeepSeek Chat), intelligent brain management, smart override logic, regime-based dynamic MIN_QUALITY, precision calculator, deep market analyzer, dynamic protection manager, balance-tiered risk profiles, auto-strategy selection, dynamic trailing SL, auto-flip multi-timeframe analysis, and a regime detection engine.
- **Adaptive Win Rate Optimizer**: Tracks recent performance, calculates Sharpe ratio, adjusts position sizing dynamically, scales SL/TP based on confidence, and incorporates regime-aware adjustments.
- **ExecutionBot**: Centralized architecture for all trade execution logic with source-aware approval gating and Stage Engine integration, ensuring 100% SL/TP protection.
- **Auto-Optimization System**: Self-adaptive trading through intelligent parameter tuning, multi-level protection, and a symbol tiering engine with dynamic blacklist management.
- **Insurance Monitor System**: Multi-layered account protection including Drawdown Protection, Margin Ratio Defense, Cross/Isolated Balancer, and a Circuit Breaker.
- **Validation & Safety Infrastructure**: Includes a Validation Pipeline, Fail-Closed Decision Gates, Monte Carlo simulations, Live Health Monitor, 3-Layer Emergency Protection System, Hedge Position Manager, Stop Order Validator, Order Hygiene System, and an enhanced SL/TP ENGINE with critical validation.
- **Hedge Mode Auto-Activation System**: Fully automatic Hedge Mode activation.
- **Smart LIMIT+MARKET Order Router**: Decision matrix for intelligent order routing.
- **Order Consolidation System**: Limits orders per symbol, auto-merges similar prices, and optimizes strategic TP levels.
- **Hybrid Dynamic Leverage System**: 100% dynamic leverage (2-35x) adapting in real-time based on ADX.
- **Trading Policy Filters**: System-wide protection via Symbol Filter Engine (100% dynamic volume filtering, liquidity, Binance whitelist/blacklist), Adaptive Volume Filter Integration, Market-Aware Threshold Selection, Order Quality Monitor, Position Limits Manager, and Trading Gatekeeper.
- **Dynamic Smart Filter**: Regime-Aware + AUTO Percentile Strategy for adaptive volume analysis, auto-percentile strategy selection, adaptive volume thresholds, regime-based RR & quality thresholds, dynamic BTC correlation penalty, adaptive direction penalty, and market intelligence integration.
- **Dynamic TOP 100 Symbol Filter**: Blocks trades for symbols outside the TOP 100.
- **Binance Symbol Validator**: Universal coverage for all order creation paths with side-aware rounding, real-time sync with Binance, graceful fallback, and precision error prevention.
- **Position Mode Management**: Prevents APIError -4061 through `POSITION_MODE_OVERRIDE`, auto-adaptation logic, centralized wrapper system, cache invalidation, retry logic fix, and startup skip logic.
- **Trade Execution Pipeline**: Calculates quantity from budget, supports HYBRID flow, and persists metadata to Redis before execution.
- **Telegram Digest System**: Consolidated notification system for batched reports.
- **Margin Gate System**: Auto-pause scanning when margin insufficient, auto-resume when funds available.
- **Critical AutoFix Engine**: Auto-detects and fixes critical issues (precision, order execution, position management, risk) with real-time monitoring and threshold-based triggers.
- **Intelligent Trading Features**: Includes Pattern Recognition Engine, Adaptive Confidence Weights, Win Rate Optimizer, and Symbol-Specific Trading Rules.
- **Quantum Trading Council System**: A 7-member expert AI council (DeepSeek, Grok, Claude, Qwen, Gemini, Falcon, Mixtral) with weighted voting for trade qualification, strategy routing, and smart token management based on budget and performance-based reallocation.
- **External Brain Integration System**: A 6-bot cooperative trading team (Cryptohopper, 3Commas, WunderTrading, HyperTrader, Bybit Signals, TradingView) with dynamic capabilities, failover, consensus merging, self-learning, real-time management, zero downtime, and API endpoints for control.

### Deployment Architecture
The production environment runs on Render.com with Background Workers and a Neon PostgreSQL database, connected to GitHub for auto-deployment. Replit is used for development.

## External Dependencies

-   **Binance Futures API**: Market data, order execution, account management.
-   **Neon PostgreSQL**: Persistent data storage.
-   **DeepSeek API**: Primary AI provider for trade optimization and consensus voting.
-   **Alibaba Cloud DashScope API**: Optional AI provider.
-   **Google Gemini API**: Optional AI provider.
-   **Anthropic Claude API**: Optional AI provider.
-   **AI-X/Grok API**: Optional fallback AI provider.
-   **Telegram Bot API**: Notifications, approval workflows, interactive callbacks, and stage engine control.
-   **N8N Workflow Automation**: External workflow integration, news ingestion.
-   **Gunicorn**: Production-grade WSGI HTTP server.
-   **Redis Cloud**: High-performance caching and temporary data storage.
-   **Cryptohopper**: External scanner for market analysis.
-   **3Commas**: External manager for smart position management.
-   **WunderTrading**: External signals relay system.
-   **HyperTrader**: External execution for fast order routing.
-   **Bybit Signals**: External futures signals.
-   **TradingView**: External webhooks & indicators.