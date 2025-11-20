# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous AI-driven algorithmic trading platform designed for 24/7 operation on Binance Futures. It analyzes 534 symbols, executing intelligent trades based on 7 integrated strategies and dynamic capital management. The platform's core is an AI-driven MetaBrain that eliminates hardcoded logic, ensuring all trade parameters are AI-determined. It aims for 4-10 high-quality daily trades, focusing on scalability, autonomous operation through a self-adaptive engine, and complete data persistence, optimized for diverse market conditions.

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
-   **Market Scanner**: Autonomous multi-timeframe (15M+1H+4H) technical analysis across Binance Futures with weighted trend detection.
-   **AI-Powered Proposals**: Uses DeepSeek Chat for trade decisions with adaptive Risk/Reward, intelligent brain management, and dynamic quality threshold enforcement.
-   **GRID Trading**: Integrated FUTURES GRID trading with dynamic symbol selection, tiered strategies, dynamic sizing, and automatic SL/TP protection.
-   **Risk Management**: Includes quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
-   **Dynamic Budget System**: Real-time trade budget calculation based on available wallet balance, trade quality, volatility, and market regime.
-   **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit.
-   **Complete Data Persistence**: All critical data is saved to a PostgreSQL database.

**MetaBrain - AI-Driven Precision Trading:**
-   **Stage Engine System**: 3-stage auto-deployment with health-based auto-promotion.
-   **1-Brain Lean Architecture**: DeepSeek Chat for autonomous trade decisions.
-   **Intelligent Brain Management**: Auto-suspends/resumes failed AI providers, dynamic consensus thresholds, cost tracking, and token budgeting.
-   **Smart Override Logic**: AI participates in decisions but respects MIN_QUALITY threshold.
-   **Regime-Based Dynamic MIN_QUALITY**: Adaptive quality thresholds based on market regime.
-   **Precision Calculator**: Calculates exact leverage and investment based on trade quality, market volatility, regime, and balance.
-   **Deep Market Analyzer & Live Regime Detector**: Multi-layer technical analysis and real-time market classification.
-   **Dynamic Protection Manager**: AI suggests regime-specific parameter sets with guardrails.
-   **Balance-Tiered Risk Profiles**: Auto-adjusts trading parameters based on 5 account tiers.
-   **Auto-Strategy Selection Engine**: Automatically chooses optimal strategy based on market conditions.
-   **Multi-Target TP System**: 3-level take profit with dynamic exit percentages and volatility-adjusted RR ratios, including dynamic TP extension.
-   **Dynamic Trailing SL**: Activates after TP1, moves Stop Loss up as price climbs, tightens progressively at higher TP levels.

**ExecutionBot - Unified Trade Execution Wrapper:**
-   Centralized architecture for all trade execution logic with source-aware approval gating and Stage Engine integration for auto-bypass.
-   **100% SL/TP Protection**: All positions receive automatic Stop Loss and Take Profit orders immediately after entry.

**Auto-Optimization System (Self-Adaptive Trading):**
-   **Intelligent Parameter Tuning**: Analyzes performance and adjusts `min_quality`, RR, and leverage.
-   **Multi-Level Protection**: Activates Warning/Conservative/Emergency modes based on performance.
-   **Symbol Tiering Engine & Dynamic Blacklist Manager**: Classifies symbols by performance and auto-blacklists underperforming ones.

**Insurance Monitor System (Account Protection):**
-   Multi-layered protection including Drawdown Protection, Margin Ratio Defense, Cross/Isolated Balancer, and a Circuit Breaker.

**Validation & Safety Infrastructure:**
-   Includes a Validation Pipeline, Fail-Closed Decision Gates, Monte Carlo simulations, Live Health Monitor, and a 3-Layer Emergency Protection System.
-   **Hedge Position Manager**: Detects and prevents dual positions, auto-resolves by closing weaker leg.
-   **Stop Order Validator**: Validates position exists before placing stop orders.
-   **Order Hygiene System**: Auto-cancels reduceOnly orders without positions, stale LIMIT orders, and stop orders with quantity mismatches.
-   **SL/TP ENGINE**: Overhaul with tick-aligned precision, ATR noise filter, TP ladder system, dynamic trailing SL, and order type intelligence.

**Hedge Mode Auto-Activation System:**
-   Fully automatic Hedge Mode activation when all positions are zero and current mode is One-Way.

**Smart LIMIT+MARKET Order Router:**
-   Decision matrix based on various factors to route orders intelligently.

**Order Consolidation System:**
-   Limits orders per symbol, auto-merges similar prices, and optimizes strategic TP levels.

**Hybrid Dynamic Leverage System:**
-   100% dynamic leverage (2-35x) adapting in real-time based on market conditions, trade quality, and multi-factor confidence scoring.

**Trading Policy Filters (System-Wide Protection):**
-   **Symbol Filter Engine**: Validates symbols based on volume, liquidity, Binance whitelist, and blacklist management.
-   **Order Quality Monitor**: Tracks fill rate, slippage, and execution speed.
-   **Position Limits Manager**: Sets max positions per symbol, total open orders, and correlation exposure limits.
-   **Trading Gatekeeper**: Unified pre-trade validation integrating all filters and Dynamic Leverage.

**Dynamic Smart Filter (Regime-Aware + AUTO Percentile Strategy):**
-   **Adaptive Volume Analyzer**: Measures real-time market-wide volume distribution and auto-adjusts thresholds based on actual conditions, not assumptions. Compares each symbol's volume against market median to determine relative strength.
-   **AUTO Percentile Strategy Selection**: System automatically selects optimal filtering strategy based on market-wide volume conditions (LOW_VOLUME, NORMAL, HIGH_VOLUME markets).
-   **Adaptive Volume Thresholds**: Volume requirements dynamically calculated from live market data using selected percentile strategy.
-   **Regime-Based RR & Quality Thresholds**: Automatically adjusts thresholds (CHOPPY, TRENDING, VOLATILE markets).
-   **Dynamic BTC Correlation Penalty**: Scales BTC penalty based on regime/mood/confidence.
-   **Adaptive Direction Penalty**: Counter-trend penalties adjust by regime strength.
-   **Market Intelligence Integration**: Queries Market Intelligence in real-time for regime/mood analysis before filtering.
-   **100% Dynamic Operation**: Zero hard-coded thresholds - all parameters measured from live market data across 591 symbols.
-   **Smart Caching**: 5-minute TTL on volume stats to balance freshness vs API efficiency.

**Dynamic TOP 100 Symbol Filter (Musical Chairs System):**
-   Blocks trades for symbols outside the TOP 100, with dynamic scheduling for continuous ranking.

**Binance Symbol Validator (100% Precision Coverage):**
-   **Universal Coverage**: ALL order creation paths (entry, SL, TP, grid, manual, guards) automatically validated via centralized `_quantize_price()` / `_quantize_qty()` functions.
-   **Side-Aware Rounding**: SELL prices round up (favorable to seller), BUY prices round down (favorable to buyer).
-   **Real-Time Sync**: Fetches live exchange info from Binance (tickSize, stepSize, minQty, minNotional) with 1-hour cache.
-   **Graceful Fallback**: If validator unavailable, falls back to legacy filter-based rounding with logging.
-   **Zero APIError -1111**: Eliminates precision errors by enforcing tick/step compliance at source.

**Trade Execution Pipeline:**
-   Calculates quantity from budget if not provided.
-   Supports HYBRID flow by passing budget instead of quantity.
-   Persists metadata to Redis before execution.

**Telegram Digest System**
Consolidated notification system for batched reports on Health, Trade/PnL, Critical Alerts, and AI Trade Reviews.

### Deployment Architecture
The production environment runs on Render.com with 11 Background Workers and a Neon PostgreSQL database, connected to GitHub for auto-deployment. Replit is used for development.

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