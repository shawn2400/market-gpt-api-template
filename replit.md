# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous algorithmic trading platform for 24/7 Binance Futures, leveraging AI (DeepSeek Chat) to analyze 534 symbols and execute intelligent trades. It integrates 7 trading strategies, dynamic capital management, and aims for 4-10 high-quality daily trades. The platform features a MetaBrain v9.1 that eliminates hardcoded logic, with all trade parameters determined by AI. It includes intelligent brain management, auto-suspend/resume for failed providers, automatic Hedge Mode activation, and is designed for scalability and autonomous operation with a self-adaptive engine and complete data persistence.

**Recent Critical Updates (November 2025):**
- **BanShield v2.1 CRITICAL Priority Fix (Nov 19)**: futures_account, futures_balance, futures_position_information now CRITICAL priority (never blocked in RED zone). Prevents budget calculation failures and ensures account info always accessible.
- **Multi-Timeframe Analysis System (Nov 19)**: Complete 15M+1H+4H multi-timeframe analysis with weighted trend detection (4H:50%, 1H:30%, 15M:20%). Fixes SHORT-only bias by validating higher timeframe trends before GRID entries. LONG trades now possible when 1H+4H bullish.
- **GRID Side Selection v2.0 (Nov 19)**: Uses 1H+4H trend consensus instead of 15M-only EMA analysis. LONG requires both 1H+4H bullish (price>EMA20, MACD>0), SHORT requires both bearish. Eliminates false signals from 15M noise.
- **BanShield v2.1 RPM Relaxation (Nov 19)**: Relaxed RPM limits from 25→45 req/min, red zone 25→42 to prevent API blocking. Zones now: Green<30, Yellow<38, Red<42 (previously Green<18, Yellow<22, Red<25).
- **Insurance Monitor Extension (Nov 19)**: MAX_LOSS_CAP increased 2%→5% to allow longer trade holding times and reduce premature exits on valid setups aligned with higher timeframes.
- **Order Hygiene Path Fix (Nov 19)**: Corrected import path from workers/order_hygiene_worker.py → utils/order_hygiene.py to eliminate FileNotFoundError crashes.
- **Multi-Target TP System v2.0 (Nov 19)**: Complete 3-level Take Profit implementation (TP1/TP2/TP3) with dynamic exit percentages (25/40/35 default, adapts to volatility/regime). BinanceSymbolValidator integration ensures precision compliance. ExecutionBot auto-attaches to all new positions, Position Monitor Layer 0 backfills existing positions. Verified working in production.
- **Hedge Mode Precision Fix (Nov 19)**: Resolved "Parameter 'reduceonly' sent when not required" error by removing reduceOnly flag in Hedge Mode. Fixed quantity/price rounding using BinanceSymbolValidator.round_quantity() and round_price() for exact stepSize/tickSize compliance.
- **Telegram Stage Commands (Nov 19)**: Full Stage Engine control via Telegram: /stage_status (status & health), /stage_promote (manual promotion), /stage_freeze (emergency stop), /stage_unfreeze (resume), /stage_logs (history).
- **Auto-Ban-Shield v2.0**: Production-ready dynamic rate limiting system with 3-tier priority (CRITICAL/NORMAL/LOW), background event loop for async/sync compatibility, complete coverage of all Binance REST endpoints including fallbacks, preventing IP bans while maintaining trading performance.
- **Emergency Kill-Switch**: Instant shutdown system with WebSocket-only mode for ban recovery, automated via GitHub-to-Render deployment.
- **Production PYTHONPATH Fix**: Resolved "No module named 'utils'" errors in Render deployment with proper Docker environment configuration.

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
-   **Dynamic Budget System**: Real-time trade budget calculation based on available wallet balance, trade quality, volatility, and market regime. Features Budget Re-Evaluation for scale-in and regime-aware multipliers.
-   **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit.
-   **Complete Data Persistence**: All critical data is saved to a PostgreSQL database.

**MetaBrain v9.1 - AI-Driven Precision Trading:**
-   **Stage Engine System**: 3-stage auto-deployment (Health Monitoring → Full Auto Trading Validation → Maximum Performance) with health-based auto-promotion and complete approval bypass for 100% dynamic automatic trading.
-   **1-Brain Lean Architecture**: DeepSeek Chat for autonomous trade decisions, with optional expansion brains.
-   **Intelligent Brain Management**: Auto-suspends/resumes failed AI providers, dynamic consensus thresholds, cost tracking, and token budgeting.
-   **Smart Override Logic**: AI participates in decisions but respects MIN_QUALITY threshold, with Stage Engine auto-approval bypass for 100% automation.
-   **Regime-Based Dynamic MIN_QUALITY**: Adaptive quality thresholds based on market regime.
-   **Precision Calculator**: Calculates exact leverage and investment based on trade quality, market volatility, regime, and balance.
-   **Deep Market Analyzer & Live Regime Detector**: Multi-layer technical analysis and real-time market classification.
-   **Dynamic Protection Manager**: AI suggests regime-specific parameter sets with guardrails.
-   **Balance-Tiered Risk Profiles**: Auto-adjusts trading parameters based on 5 account tiers.
-   **Auto-Strategy Selection Engine**: Automatically chooses optimal strategy based on market conditions.
-   **Multi-Target TP System v2.0**: 3-level take profit with dynamic exit percentages and volatility-adjusted RR ratios.
-   **Trailing TP Fix**: Activates at 50% profit (not 25%), trails 10% from peak (not 15%) to allow TP2/TP3 execution.

**ExecutionBot - Unified Trade Execution Wrapper:**
-   Centralized architecture for all trade execution logic with source-aware approval gating.
-   **Stage Engine Integration**: Auto-bypass approvals when Stage Engine enable_auto_trading=True, enabling 100% dynamic automatic trading in all stages.
-   **100% SL/TP Protection**: All positions receive automatic Stop Loss and Take Profit orders immediately after entry, with emergency closure if placement fails.

**Auto-Optimization System (Self-Adaptive Trading):**
-   **Intelligent Parameter Tuning**: Analyzes performance and adjusts `min_quality`, RR, and leverage.
-   **Multi-Level Protection**: Activates Warning/Conservative/Emergency modes based on performance.
-   **Symbol Tiering Engine & Dynamic Blacklist Manager**: Classifies symbols by performance and auto-blacklists underperforming ones.

**Trailing TP System:**
-   Auto-activates at 25-30% profit and dynamically adjusts trailing distance.

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