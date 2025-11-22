# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous AI-driven algorithmic trading platform designed for 24/7 operation on Binance Futures. It analyzes 534 symbols, executing intelligent trades based on 7 integrated strategies and dynamic capital management. The platform's core is an AI-driven MetaBrain that eliminates hardcoded logic, ensuring all trade parameters are AI-determined. It aims for 4-10 high-quality daily trades, focusing on scalability, autonomous operation through a self-adaptive engine, and complete data persistence, optimized for diverse market conditions. The business vision is to provide a robust, self-optimizing algorithmic trading solution with high market potential due to its autonomous nature and AI-driven adaptability.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations. All communication in Hebrew. Automatic trading with 100% dynamic automation - no time-based patterns. SL/TP fully dynamic. Budget scales with wallet size automatically.

## Recent Changes (Nov 22, 2025 - v9.3.6 Dynamic Leverage Enabled + v9.3.5 SLTP Safety)

### MetaBrain v9.3.6 - Dynamic Leverage Enabled ✅ (CRITICAL - LEVERAGE FIX)
- **Files**: `utils/leverage_policy.py` (FIXED - DEFAULT ENABLED)
- **THE LEVERAGE MYSTERY SOLVED**:
  1. **❌ ROOT CAUSE FOUND**: `leverage_policy.py` had `DYNAMIC_LEVERAGE_MODE = os.getenv("DYNAMIC_LEVERAGE_MODE", "0")` 
     - Default was "0" (DISABLED) - עוד! המינוף לא היה דינמי כי הוא היה נטורל כברירת מחדל!
  2. **✅ FIX APPLIED**: Changed default to "1" → **Dynamic Leverage NOW ENABLED BY DEFAULT**
  3. **📊 What This Means**:
     - Leverage now calculated by `DynamicLeverageCalculator` 
     - Multi-factor confidence scoring (Quality, Market, Tier, WinRate, ATR)
     - 4-Layer safety guards (Emergency, Volatility, Symbol, Portfolio)
     - Market regime detection (TRENDING/VOLATILE/CHOPPY/CRASH)
     - Recovery mode after losses
     - Real-time performance tracking
  4. **✅ Leverage Range**: 2-35x (fully dynamic, no more "static" leverage)
- **Status**: ✅ Dynamic Leverage NOW ACTIVE - מינוף אמיתי דינמי 100%!

### MetaBrain v9.3.5 - SLTP Safety Guard + TP Rounding Fix ✅ (CRITICAL FIXES)
- **Files**: `utils/sltp_safety_guard.py` (NEW), `utils/sl_movement_freeze.py` (NEW), `utils/multi_target_tp.py` (UPDATED), `utils/tp_ladder.py` (UPDATED)
- **CRITICAL FIXES** (סוף לשגיאות!):
  1. **🛡️ SLTP Safety Guard** (NEW):
     - Validates ALL SL/TP prices BEFORE sending to Binance
     - SL must be > 0 AND logically correct for side (LONG/SHORT)
     - TP must be > 0 AND logically correct for side
     - BLOCKS orders with invalid prices (never sends bad orders)
  2. **❄️ SL Movement Freeze** (NEW):
     - Prevents loosening SL (moving away from breakeven)
     - Only tightens SL if improvement > 5%
     - Stops unnecessary SL changes (no more "every 5 seconds" updates)
  3. **✅ TP Rounding Fix** (CRITICAL):
     - Fixed: TP prices rounding to 0.0 (causing -4006 API errors)
     - Guard in `_normalize_price()` prevents rounding to 0
     - If rounding would destroy value, uses original unrounded price
     - Prevents micro-cap tokens (A2ZUSDT, 1000RATSUSDT) from failing
  4. **📊 Dynamic SL/TP Validation**:
     - Entry price validation at calculation start
     - Risk amount sanity checks (minimum 0.1%)
     - Post-rounding validation for both SL and TP
  5. **Prevents**:
     - ❌ SL <= 0 orders
     - ❌ TP <= 0 orders
     - ❌ TP rounding to 0 (micro-cap fix)
     - ❌ LONG SL >= Entry (must be below)
     - ❌ SHORT SL <= Entry (must be above)
     - ❌ Loosening position protection
- **Status**: ✅ SLTP validation STRICT + Rounding Protection - Zero invalid orders!

### MetaBrain v9.3.4 - Smart Token Budget Management ✅
- **Files**: `utils/token_budget_manager.py` (NEW), `utils/ai_decision_maker.py` (UPDATED)
- **SMART BRAIN SUSPENSION SYSTEM**:
  1. **6 AI Brains Connected** (all cost-aware):
     - Qwen 2.5 Turbo: FREE ✅ (always active)
     - DeepSeek: $0.0001/call (ultra-cheap)
     - Gemini 2 Pro: $0.00005/call (very cheap)
     - GPT-4o Mini: $0.0005/call (cheap)
     - Grok (XAI): $0.0008/call (mid-cost)
     - Claude (Anthropic): $0.003/call (premium)
  2. **Intelligent Suspension/Resume**:
     - Balance < $5.0 → SUSPEND all paid brains (except Qwen)
     - Balance ≥ $10.0 → RESUME in priority order (cheap→expensive)
     - Qwen (FREE) always active
  3. **Budget Tracking** - Every call tracked, no waste
  4. **Dynamic Consensus** - Only active brains vote
- **Status**: ✅ Smart budget management enabled - סוכנים וסוגרים בחוכמה!

## System Architecture

### UI/UX
The system provides a dashboard UI and enhanced Telegram notifications, utilizing HTML formatting, emojis, and inline interactive buttons for user interaction.

### Technical Implementations
The core application is built with FastAPI and Gunicorn, emphasizing modularity and policy management via YAML files. All critical data is saved to a PostgreSQL database.

**Core Features:**
- **Automated Trading Modes**: Supports MARKET, HYBRID, and FULL AUTO execution.
- **Live Trade Management**: Dynamic management of open positions with TP, SL, BE logic, ATR-based trailing stops, and auto-flip position reversal.
- **Market Scanner**: Autonomous multi-timeframe (15M+1H+4H) technical analysis across Binance Futures with weighted trend detection.
- **AI-Powered Proposals**: Uses DeepSeek Chat for trade decisions with adaptive Risk/Reward, intelligent brain management, and dynamic quality threshold enforcement.
- **GRID Trading**: Integrated FUTURES GRID trading with dynamic symbol selection, tiered strategies, dynamic sizing, and automatic SL/TP protection.
- **Risk Management**: Includes quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
- **Dynamic Budget System**: 100% dynamic trade budget calculation based on equity-tied ceiling, quality multiplier, volatility adjustment, and floor/cap. Auto-detects wallet balance and dynamically scales all trading parameters based on balance tiers.
- **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit with multi-target TP (up to 5 levels).
- **MetaBrain - AI-Driven Precision Trading**: Features a 3-stage auto-deployment engine, 1-Brain Lean Architecture (DeepSeek Chat), intelligent brain management, smart override logic, regime-based dynamic MIN_QUALITY, precision calculator for leverage/investment, deep market analyzer, dynamic protection manager, balance-tiered risk profiles, auto-strategy selection, dynamic trailing SL, auto-flip multi-timeframe analysis, and a regime detection engine.
- **Adaptive Win Rate Optimizer**: Tracks recent performance, calculates Sharpe ratio, adjusts position sizing dynamically, scales SL/TP based on confidence, and incorporates regime-aware adjustments.
- **ExecutionBot**: Centralized architecture for all trade execution logic with source-aware approval gating and Stage Engine integration, ensuring 100% SL/TP protection.
- **Auto-Optimization System**: Self-adaptive trading through intelligent parameter tuning, multi-level protection (Warning/Conservative/Emergency modes), and a symbol tiering engine with dynamic blacklist management.
- **Insurance Monitor System**: Multi-layered account protection including Drawdown Protection, Margin Ratio Defense, Cross/Isolated Balancer, and a Circuit Breaker.
- **Validation & Safety Infrastructure**: Includes a Validation Pipeline, Fail-Closed Decision Gates, Monte Carlo simulations, Live Health Monitor, 3-Layer Emergency Protection System, Hedge Position Manager, Stop Order Validator, Order Hygiene System, and an enhanced SL/TP ENGINE. Includes critical validation for quantity, TP price, and position limits to prevent API errors.
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