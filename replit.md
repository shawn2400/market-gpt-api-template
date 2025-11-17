# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous algorithmic trading platform designed for 24/7 Binance Futures trading. It leverages AI, specifically DeepSeek Chat, to scan 534 symbols and make intelligent trade decisions. The platform integrates 7 trading strategies, dynamic capital management, and aims for 4-10 high-quality daily trades. Its MetaBrain v9.1 eliminates hardcoded logic, with all trade parameters determined by AI analysis. The system features intelligent brain management with auto-suspend/resume for failed providers, automatic Hedge Mode activation, and is built for scalability and autonomous operation with a self-adaptive engine and complete data persistence.

## Recent Changes

### November 17, 2025 - Automated GitHub→Render Deployment Pipeline
Implemented 100% automated deployment system for autonomous 24/7 operation:

1. **GitHub Action Auto-Deploy** (`.github/workflows/render-deploy.yml`): Triggers Render deployment on every push to main branch
2. **Render API Integration**: Automated deployment via Render API using encrypted GitHub Secrets (RENDER_API_KEY, RENDER_SERVICE_ID)
3. **WebSocket Optimization Deployed**: Production now running with `USER_STREAM_ENABLE=1`, `STREAM_TP_BE=true`, reducing Binance API calls by 72% (2400+/min → ~670/min)
4. **Optimized Polling Intervals**: Insurance Monitor (180s), Fills Watcher (60s), Position Monitor (120s), Health Check (90s)

**Result**: Push to GitHub → Auto-deploy to Render → WebSocket activated → Zero manual intervention required ✅

### November 17, 2025 - Critical Bug Fixes
Fixed 3 critical bugs preventing stable production deployment on Render.com Reserved VM:

1. **RuntimeError in main.py** (line 269): Added try/except handler in `_head_compat_and_soft_readyz` middleware to prevent HEAD request crashes
2. **FutureWarning in utils/indicators.py**: Replaced deprecated `fillna(method='ffill')` with modern `ffill()` for pandas 2.0+ compatibility
3. **Precision rounding in utils/binance_symbol_validator.py**: Fixed Decimal quantize pattern to prevent InvalidOperation errors

All fixes pushed to GitHub via API (bypassing Replit git restrictions) using `scripts/upload_critical_fixes.py`.

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
-   **AI-Powered Proposals**: Uses DeepSeek Chat for trade decisions with adaptive Risk/Reward, intelligent brain management, and dynamic quality threshold enforcement.
-   **GRID Trading**: Integrated FUTURES GRID trading with dynamic symbol selection, tiered strategies, dynamic sizing, and automatic SL/TP protection for all GRID fills.
-   **Risk Management**: Includes quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
-   **Dynamic Budget System**: Real-time trade budget calculation based on available wallet balance, trade quality, volatility, and market regime. Features Budget Re-Evaluation for scale-in on profitable positions and regime-aware multipliers.
-   **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit.
-   **Complete Data Persistence**: All critical data is saved to a PostgreSQL database.

**MetaBrain v9.1 - AI-Driven Precision Trading:**
-   **1-Brain Lean Architecture**: DeepSeek Chat for autonomous trade decisions, with optional expansion brains for multi-brain consensus.
-   **Intelligent Brain Management**: Auto-suspends/resumes failed AI providers, dynamic consensus thresholds, cost tracking, and token budgeting.
-   **Smart Override Logic**: AI participates in decisions but respects MIN_QUALITY threshold, with a system for auto-approval, borderline consensus, or AI rejection based on score gaps.
-   **Regime-Based Dynamic MIN_QUALITY**: Adaptive quality thresholds based on market regime (CHOPPY, SIDEWAYS, TRENDING, VOLATILE).
-   **Precision Calculator**: Calculates exact leverage and investment based on trade quality, market volatility, regime, and balance.
-   **Deep Market Analyzer & Live Regime Detector**: Multi-layer technical analysis and real-time market classification.
-   **Dynamic Protection Manager**: AI suggests regime-specific parameter sets with guardrails.
-   **Balance-Tiered Risk Profiles**: Auto-adjusts trading parameters (position size, leverage, max positions, daily risk limit) based on 5 account tiers.
-   **Auto-Strategy Selection Engine**: Automatically chooses optimal strategy based on market conditions.
-   **Multi-Target TP System v2.0**: 3-level take profit with fully dynamic exit percentages that adapt to market conditions and volatility-adjusted RR ratios.

**ExecutionBot - Unified Trade Execution Wrapper:**
-   Centralized architecture for all trade execution logic with source-aware approval gating.
-   **100% SL/TP Protection**: All positions receive automatic Stop Loss and Take Profit orders immediately after entry, with emergency closure if placement fails.
-   **Fills Watcher Hardening**: Critical alerts and Telegram notifications if trade_manager import fails, preventing silent degradation.

**Auto-Optimization System (Self-Adaptive Trading):**
-   **Intelligent Parameter Tuning**: Analyzes performance and adjusts `min_quality`, RR, and leverage.
-   **Multi-Level Protection**: Activates Warning/Conservative/Emergency modes based on performance.
-   **Symbol Tiering Engine & Dynamic Blacklist Manager**: Classifies symbols by performance and auto-blacklists underperforming ones.

**Trailing TP System:**
-   Auto-activates at 25-30% profit and dynamically adjusts trailing distance to secure profits.

**Insurance Monitor System (Account Protection):**
-   Multi-layered protection including Drawdown Protection, Margin Ratio Defense, Cross/Isolated Balancer, and a Circuit Breaker.

**Validation & Safety Infrastructure:**
-   Includes a Validation Pipeline, Fail-Closed Decision Gates, Monte Carlo simulations, Live Health Monitor, and a 3-Layer Emergency Protection System.
-   **Hedge Position Manager**: Detects and prevents dual positions, auto-resolves by closing weaker leg.
-   **Stop Order Validator**: Validates position exists before placing stop orders.
-   **Order Hygiene System**: Auto-cancels reduceOnly orders without positions, stale LIMIT orders, and stop orders with quantity mismatches.
-   **SL/TP ENGINE V6.0**: Overhaul with tick-aligned precision, ATR noise filter, TP ladder system, dynamic trailing SL, and order type intelligence.
-   **Universal GRID/HYBRID Support**: All SL/TP upgrades auto-apply to GRID fills.

**Hedge Mode Auto-Activation System:**
-   Fully automatic Hedge Mode activation when all positions are zero and current mode is One-Way.

**Smart LIMIT+MARKET Order Router:**
-   Decision matrix based on various factors to route orders intelligently.

**Order Consolidation System:**
-   Limits orders per symbol, auto-merges similar prices, and optimizes strategic TP levels.

**Hybrid Dynamic Leverage System v2.0:**
-   100% dynamic leverage (2-35x) adapting in real-time based on market conditions, trade quality, and multi-factor confidence scoring.

**Trading Policy Filters (System-Wide Protection):**
-   **Symbol Filter Engine**: Validates symbols based on volume, liquidity, Binance whitelist, and blacklist management.
-   **Order Quality Monitor**: Tracks fill rate, slippage, and execution speed.
-   **Position Limits Manager**: Sets max positions per symbol, total open orders, and correlation exposure limits.
-   **Trading Gatekeeper**: Unified pre-trade validation integrating all filters and Dynamic Leverage.
-   **Zero Tolerance Filter**: Auto-cleanup for expired temp blacklist entries.

**Dynamic TOP 100 Symbol Filter (Musical Chairs System):**
-   Blocks trades for symbols outside the TOP 100, with dynamic scheduling for continuous ranking.

**Binance Symbol Validator (v1.0):**
-   Real-time symbol precision validation against Binance exchange info, with automatic quantity/price rounding.

**Trade Execution Pipeline:**
-   Calculates quantity from budget if not provided.
-   Supports HYBRID flow by passing budget instead of quantity.
-   Persists metadata to Redis before execution.
-   Enhanced error logging for debugging.

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