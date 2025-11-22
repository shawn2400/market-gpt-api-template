# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous AI-driven algorithmic trading platform for 24/7 operation on Binance Futures. It analyzes 534 symbols, executing intelligent trades based on 7 integrated strategies and dynamic capital management. The platform features an AI-driven MetaBrain that determines all trade parameters, aiming for 4-10 high-quality daily trades. It prioritizes scalability, autonomous operation through a self-adaptive engine, and complete data persistence, optimized for diverse market conditions. The business vision is to provide a robust, self-optimizing algorithmic trading solution with high market potential due to its autonomous and AI-driven adaptability.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations. All communication in Hebrew. Automatic trading with 100% dynamic automation - no time-based patterns. SL/TP fully dynamic. Budget scales with wallet size automatically.

## Recent Changes (Nov 22, 2025 - v9.3.8+ HOTFIX)

### 🔥 v9.3.8+ HOTFIX - Critical Variable Scope Bug

**EMERGENCY FIX: Position Monitor Variable Scope Error** 🐛
- **File**: `workers/position_monitor.py` (line 1055)
- **Bug**: Line 1052 referenced undefined variable `p.get("markPrice")` causing NameError exception
- **Fix**: Changed to use available variables `mark_price` (from line 998 context) instead of undefined `p`
  - Before: `current_price = float(p.get("markPrice", p.get("entryPrice", 0)))`
  - After: `current_price = mark_price if mark_price > 0 else entry_price`
- **Impact**: Position Monitor TP update was throwing exceptions repeatedly - now ✅ FIXED
- **Status**: ✅ Verified working - zero errors in Position Monitor logs

---

### ✅ v9.3.8 - 3 Critical Fixes (Leverage + Budget MAX + Position Remnants)

**FIX #1: Aggressive Leverage Mapping** 🚀
- **File**: `utils/dynamic_leverage.py` (lines 419-455)
- **Problem**: Leverage always stayed at 2-3x because confidence score mapping was too conservative
- **Solution**: Updated `_map_confidence_to_leverage()` with 9 tiers (3-35x range):
  - Score 9.5-10.0: 32-35x (highest conviction)
  - Score 9.0-9.4: 28-32x (trending high quality)
  - Score 8.5-8.9: 24-30x (strong trades)
  - Score 8.0: 20-25x
  - Score 7.0: 15-20x
  - Score 6.0: 12-18x
  - Score 5.0: 8-12x
  - Score < 5.0: 3-6x (defensive)
- **Result**: ✅ Full 2-35x leverage range now active (no more stuck at 2-3x)

**FIX #2: Quality-Based MAX Enforcement** 💰
- **File**: `utils/dynamic_budget_manager.py` (lines 154-174)
- **Problem**: Position size had static $100 MAX regardless of trade quality
- **Solution**: Added dynamic MAX based on quality_score:
  - Quality 9.0+: MAX $200 (premium trades)
  - Quality 8.5+: MAX $175
  - Quality 8.0+: MAX $150
  - Quality 7.5+: MAX $125
  - Quality 7.0+: MAX $100
  - Quality 6.5+: MAX $75
  - Quality 6.0+: MAX $50
  - Quality < 6.0: MAX $25 (minimum only)
- **Result**: ✅ Position sizing now scales intelligently with trade quality

**FIX #3: Skip Tiny Position Remnants** 💵
- **Files**: `workers/position_monitor.py` (lines 1054-1072)
- **Problem**: System tried to place TP orders on cents (e.g., $0.001 positions) - wasted spread/slippage
- **Solution**: Added minimum position value check:
  - Skip TP placement if total position < $0.05 USD
  - Skip individual TP if its value < $0.05 USD
  - Log warnings for skipped remnants
- **Result**: ✅ No more placing TP orders on tiny cents that aren't profitable

**Status**: ✅ All 3 fixes ACTIVE and verified - מינוף אמיתי, תקציב חכם, אין סנטים מיותרים!

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
---

## Quantum Exploratory Features (v9.3.8+ Testing)

### 🧠 3 New "Quantum" Learning Engines (Hybrid Approach)

**Phase 1: Testing Mode** - Running in parallel with existing 11 workers

**Engine #1: Pattern Recognition** 
- **File**: `utils/quantum_pattern_engine.py`
- **What it does**: Learns from recent 50 winning trades, detects repeating patterns
- **Example**: "When quality score = 8.5 + TRENDING + ATR 2% = usually wins" → boost confidence
- **Current status**: Collecting trade history
- **Expected impact**: +5-15% confidence on proven patterns

**Engine #2: Adaptive Confidence Scoring**
- **File**: `utils/adaptive_confidence_scorer.py`  
- **What it does**: Adjusts confidence weights based on recent market regime performance
- **Example**: If TRENDING regime has 70% win rate last week → boost market weight from 25% to 33%
- **Current status**: Tracking regime performance
- **Expected impact**: Better signal quality in winning market conditions

**Engine #3: Market Regime Predictor**
- **File**: `utils/market_regime_predictor.py`
- **What it does**: Predicts NEXT regime (1-4 hours ahead) before it happens
- **Example**: Detects ADX falling → predicts CHOPPY is coming → proactively reduce leverage
- **Current status**: Building history
- **Expected impact**: Earlier exits from bad regimes, proactive strategy adjustment

**Integration**:
- **File**: `utils/quantum_system_integrator.py`
- **Purpose**: Wraps all 3 engines, plugs into existing strategy pipeline
- **How it works**: `enhance_trade_proposal()` applies all 3 engines to trade scoring

**Rollout Plan**:
1. ✅ Created all 3 engines (DONE)
2. ⏳ Phase 1: Test in parallel for 1-2 weeks
3. ⏳ Phase 2: Measure impact vs baseline
4. ⏳ Phase 3: Full integration if positive (>10% improvement)
5. ⏳ Phase 4: Abandon if negative (automatic fallback to v9.3.8)

**Risk Level**: LOW
- Engines run in parallel (non-blocking)
- Can be instantly disabled if underperforming
- Existing 11 workers continue normally

---
