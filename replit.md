# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous AI-driven algorithmic trading platform for 24/7 operation on Binance Futures. It analyzes 534 symbols, executing intelligent trades based on 7 integrated strategies and dynamic capital management. The platform's core is an AI-driven MetaBrain that eliminates hardcoded logic, ensuring all trade parameters are AI-determined. It aims for 4-10 high-quality daily trades, focusing on scalability, autonomous operation through a self-adaptive engine, and complete data persistence, optimized for diverse market conditions. The business vision is to provide a robust, self-optimizing algorithmic trading solution with high market potential due to its autonomous nature and AI-driven adaptability.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations. All communication in Hebrew. Automatic trading with 100% dynamic automation - no time-based patterns. SL/TP fully dynamic. Budget scales with wallet size automatically.

## Recent Changes (Nov 22, 2025)

### MetaBrain v9.2.7 - Critical Fixes 🔧
- **Files**: `workers/position_monitor.py`, `utils/auto_flip.py`
- **Fixes**:
  1. **SL Not Rising** - Removed hold period skip (lines 817-820) - SL now updates via breakeven/trailing during hold period
  2. **AutoFlip Execution** - Implemented actual position reversal logic based on multi-TF consensus
  3. **Grade Trades** - Verified working correctly, trades sent via _emit() when passing quality threshold
- **Impact**: ✅ SL protection active immediately, AutoFlip executes on alignment, Trading pipeline confirmed working
- **Status**: ✅ ACTIVE - All critical workflows restarted and verified

### MetaBrain v9.2.6 - Automatic Resource Management 💰
- **Files**: `utils/margin_gate.py`, `workers/gpt_auto_suggest.py`, `workers/gpt5_orchestrator.py`
- **Feature**: Smart Resource Pausing - Automatic pause/resume based on available margin
- **Behavior**:
  - ⏸️ **PAUSES** when margin < $10: Auto Scanner, GPT-5, Brain Analysis
  - 🔄 **FAST POLLING**: Checks every 10 seconds for freed margin
  - ✅ **AUTO-RESUMES**: No manual intervention needed when margin returns (from profit/deposit)
  - 📊 **NO WASTED API CALLS**: Prevents resource waste when account can't trade
- **Impact**: Zero resource waste when budget depleted - system sleeps efficiently
- **Status**: ✅ ACTIVE - Scanning pauses automatically when insufficient margin

### MetaBrain v9.2.5.2 - Position Limits Fix 🔧
- **File**: `utils/position_limits.py` (line 179)
- **Fix**: Changed `>=` to `>` in _check_total_open_orders()
- **Issue**: System was blocking trades at exactly 25 orders (should allow 25, only block at 26+)
- **Impact**: ACTUSDT execution now works with 25 open orders
- **Status**: ✅ FIXED - Executions can now proceed normally

### MetaBrain v9.2.5.1 - AutoFix Validation Hotfix ✅
- **Files**: `utils/critical_autofix_engine.py` (validation methods)
- **Fixes**: 
  - Replaced strict byte/string matching with flexible comparison (b"true", "true", True)
  - Fixed fail-open validation design - Redis unavailable no longer causes rollback
  - Allows transient failures instead of rolling back fixes
- **Result**: ✅ AIOUSDT_TP_ROUNDING fix now validates and applies successfully
- **Status**: ✅ VERIFIED - AutoFix engine now works without validation rollbacks

### MetaBrain v9.2.5 - Critical AutoFix Engine ✅
- **Files**: `utils/critical_autofix_engine.py`, `utils/critical_issues_monitor.py` (720 lines total)
- **Features**: Auto-detects & fixes 10 critical issues (precision, order execution, position management, risk)
- **Monitoring**: Real-time alert system with 8+ threshold-based triggers
- **Integration**: Embedded in Auto Scanner worker (runs every cycle)
- **Status**: ✅ ACTIVE - Auto-remediating critical issues before they cause losses

### MetaBrain v9.2.4 - Adaptive Budget Engine ✅
- **File**: `utils/adaptive_budget_engine.py` (auto-scales budget based on balance)
- **Features**: 5-tier auto-scaling system ($5-50 per trade based on account size)
- **MIN_INVESTMENT_USD**: Reduced $50 → $15 (temporary for low balance)
- **Status**: ✅ ACTIVE - System auto-scales as balance grows

### MetaBrain v9.2.3 - Profit Margin Optimization ✅
- **Budget**: Increased $25 → $50 per trade
- **TP Targets**: Widened to 100%-150%-250% RR levels
- **Quality Filter**: Raised to 5.5 minimum
- **Status**: ✅ VERIFIED in production

## System Architecture

### UI/UX
The system provides a dashboard UI and enhanced Telegram notifications, utilizing HTML formatting, emojis, and inline interactive buttons for user interaction.

### Technical Implementations
The core application is built with FastAPI and Gunicorn, emphasizing modularity and policy management via YAML files. All critical data is saved to a PostgreSQL database.

**Core Features:**
- **Automated Trading Modes**: Supports MARKET, HYBRID, and FULL AUTO execution.
- **Live Trade Management**: Dynamic management of open positions with TP, SL, BE logic, ATR-based trailing stops, and **auto-flip position reversal**.
- **Market Scanner**: Autonomous multi-timeframe (15M+1H+4H) technical analysis across Binance Futures with weighted trend detection.
- **AI-Powered Proposals**: Uses DeepSeek Chat for trade decisions with adaptive Risk/Reward, intelligent brain management, and dynamic quality threshold enforcement.
- **GRID Trading**: Integrated FUTURES GRID trading with dynamic symbol selection, tiered strategies, dynamic sizing, and automatic SL/TP protection.
- **Risk Management**: Includes quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
- **Dynamic Budget System**: 100% dynamic trade budget calculation based on equity-tied ceiling, quality multiplier, volatility adjustment, and floor/cap. Auto-detects wallet balance and dynamically scales all trading parameters based on balance tiers.
- **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit with multi-target TP (TP1/TP2/TP3). Includes critical fix for SL/TP desynchronization.
- **MetaBrain - AI-Driven Precision Trading**: Features a 3-stage auto-deployment engine, 1-Brain Lean Architecture (DeepSeek Chat), intelligent brain management, smart override logic, regime-based dynamic MIN_QUALITY, precision calculator for leverage/investment, deep market analyzer, dynamic protection manager, balance-tiered risk profiles, auto-strategy selection, **dynamic trailing SL**, **auto-flip multi-timeframe analysis**, and a regime detection engine.
- **Adaptive Win Rate Optimizer**: Tracks recent performance, calculates Sharpe ratio, adjusts position sizing dynamically (1-5%), scales SL/TP based on confidence, and incorporates regime-aware adjustments.
- **ExecutionBot**: Centralized architecture for all trade execution logic with source-aware approval gating and Stage Engine integration, ensuring 100% SL/TP protection.
- **Auto-Optimization System**: Self-adaptive trading through intelligent parameter tuning, multi-level protection (Warning/Conservative/Emergency modes), and a symbol tiering engine with dynamic blacklist management.
- **Insurance Monitor System**: Multi-layered account protection including Drawdown Protection, Margin Ratio Defense, Cross/Isolated Balancer, and a Circuit Breaker.
- **Validation & Safety Infrastructure**: Includes a Validation Pipeline, Fail-Closed Decision Gates, Monte Carlo simulations, Live Health Monitor, 3-Layer Emergency Protection System, Hedge Position Manager, Stop Order Validator, Order Hygiene System, and an enhanced SL/TP ENGINE.
- **Hedge Mode Auto-Activation System**: Fully automatic Hedge Mode activation.
- **Smart LIMIT+MARKET Order Router**: Decision matrix for intelligent order routing.
- **Order Consolidation System**: Limits orders per symbol, auto-merges similar prices, and optimizes strategic TP levels.
- **Hybrid Dynamic Leverage System**: 100% dynamic leverage (2-35x) adapting in real-time.
- **Trading Policy Filters**: System-wide protection via Symbol Filter Engine (100% dynamic volume filtering, liquidity, Binance whitelist/blacklist), Adaptive Volume Filter Integration, Market-Aware Threshold Selection, Order Quality Monitor, Position Limits Manager, and Trading Gatekeeper.
- **Dynamic Smart Filter**: Regime-Aware + AUTO Percentile Strategy for adaptive volume analysis, auto-percentile strategy selection, adaptive volume thresholds, regime-based RR & quality thresholds, dynamic BTC correlation penalty, adaptive direction penalty, and market intelligence integration.
- **Dynamic TOP 100 Symbol Filter**: Blocks trades for symbols outside the TOP 100.
- **Binance Symbol Validator**: Universal coverage for all order creation paths with side-aware rounding, real-time sync with Binance, graceful fallback, and precision error prevention.
- **Position Mode Management**: Prevents APIError -4061 through `POSITION_MODE_OVERRIDE`, auto-adaptation logic, centralized wrapper system, cache invalidation, retry logic fix, and startup skip logic.
- **Trade Execution Pipeline**: Calculates quantity from budget, supports HYBRID flow, and persists metadata to Redis before execution.
- **Telegram Digest System**: Consolidated notification system for batched reports.
- **Margin Gate System**: Auto-pause scanning when margin insufficient, auto-resume when funds available.

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
