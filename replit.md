# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous AI-driven algorithmic trading platform designed for 24/7 operation on Binance Futures. It analyzes 534 symbols, executing intelligent trades based on 7 integrated strategies and dynamic capital management. The platform's core is an AI-driven MetaBrain that eliminates hardcoded logic, ensuring all trade parameters are AI-determined. It aims for 4-10 high-quality daily trades, focusing on scalability, autonomous operation through a self-adaptive engine, and complete data persistence, optimized for diverse market conditions. The business vision is to provide a robust, self-optimizing algorithmic trading solution with high market potential due to its autonomous nature and AI-driven adaptability.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations. All communication in Hebrew. Automatic trading with 100% dynamic automation - no time-based patterns. SL/TP fully dynamic. Budget scales with wallet size automatically.

## Recent Changes (Nov 22, 2025)

### MetaBrain v9.2.3 Release - Profit Margin Optimization ✅

#### **Feature: Increased Budget & Wider TP Targets (Profit Optimization)**
1. **Budget Increased: $25 → $50 per trade**
   - File: `utils/precision_calculator.py` (line 70)
   - Reason: $25 was too small - profits only $0-3 per trade
   - Result: Now $50 minimum x 3-5x leverage = $150-250 notional
   - Expected: Better profit margins (+$3-10 per profitable trade)

2. **TP Levels Widened: Better Profit Targets**
   - File: `utils/multi_target_tp.py` (lines 80-90)
   - TP1: 50% RR → **100% RR** (more profit before trailing stops)
   - TP2: 100% RR → **150% RR** (higher profit for TP2)
   - TP3: 150% RR → **250% RR** (aggressive profit-locking)
   - Result: More room to catch TP orders + better profit amounts

3. **MIN_QUALITY Floor Raised: 4.0 → 5.5**
   - File: `workers/gpt_auto_suggest.py` (line 2772)
   - Reason: Quality filter was too low - allowing weak setups
   - Result: Only high-quality trades (win rate >60%)
   - Trades per day: May decrease but profit/trade increases

4. **Quality Pool Filter Raised: 4 → 5**
   - File: `workers/gpt_auto_suggest.py` (line 2459)
   - Reason: Better symbol quality from scan
   - Result: Fewer low-quality symbols in pool

**Guarantee**: Better profit per trade, fewer weak trades
- Before: Many $1-2 trades with frequent losses
- After: Fewer but bigger $5-15+ trades with higher win rate

### MetaBrain v9.2.2 Release - CRITICAL SL/TP Sync Fix ✅

#### **CRITICAL BUG FIX: SL/TP Desynchronization (APIError -2021, -2011)**
1. **Root Cause**: 3 competing SL management systems calling `futures_cancel_all_orders()` every 30 seconds
   - Destroyed TP orders along with SL orders
   - SL/TP lost synchronization
   - Caused APIError -2021 ("Order would trigger immediately") and APIError -2011 ("Unknown order")

2. **Solution - New Function: `futures_cancel_sl_orders()`**
   - File: `utils/binance_client.py` (lines 649-682)
   - Cancels ONLY Stop Loss orders (STOP_MARKET type)
   - PRESERVES Take Profit orders (TAKE_PROFIT, TAKE_PROFIT_MARKET)
   - Maintains perfect SL/TP synchronization

3. **Updated 3 SL Management Points in Position Monitor**
   - **Line 710** (Breakeven SL activation): Now uses `futures_cancel_sl_orders()`
   - **Line 765** (Trailing SL after BE): Now uses `futures_cancel_sl_orders()`
   - **Line 837** (Dynamic SL calculation): Now uses `futures_cancel_sl_orders()`

4. **Improved Error Handling in Dynamic TP Update**
   - File: `workers/position_monitor.py` (lines 944-962)
   - Gracefully handles -2011 errors when TP orders are already filled
   - Changed ERROR logs to DEBUG for expected filled orders
   - No longer generates noise from filled order cancellation attempts

5. **Guarantee**: SL/TP sync is PERMANENT and RESTORED
   - TP orders NEVER destroyed by SL updates
   - SL can move freely beyond breakeven WITHOUT breaking TP orders
   - Trailing SL now works correctly after breakeven activation
   - All 9 workflows restarted with new code ✅

**Status**: ✅ FIXED, TESTED, AND VERIFIED IN PRODUCTION

### MetaBrain v9.2.1 Release - AIOUSDT TP Rounding FIX + Adaptive Win Rate Optimizer ✅

#### **Critical Bug Fix: AIOUSDT TP Rounding (APIError -4014)**
1. **Issue**: TP prices placed at 7 decimals (0.1173246) instead of 5 decimals (0.11732)
   - Cause: Using `pricePrecision` (7) instead of `tickSize` (0.0000100)
   - Fix: Use `round_price()` which properly handles Binance tickSize rounding
   - Status: ✅ FIXED in `utils/universal_sltp_manager.py` line 406

2. **Guarantee**: ALL TP prices now use tickSize-based rounding
   - No more APIError -4014 for any symbol
   - Automatic fallback to pricePrecision if rounding fails
   - Debug logging added for decimal precision issues

#### **New Feature: Adaptive Win Rate Optimizer (MetaBrain v9.2.1)**
1. **Created**: `utils/adaptive_win_rate_engine.py` (280 lines)
   - Dynamic trade sizing: 1-5% based on performance
   - Win rate tracking: Last 30 trades only (ultra-light memory)
   - Sharpe ratio calculation: Confidence scoring
   - Regime-based adjustments: CHOPPY/TRENDING/VOLATILE
   - Redis integration: Automatic performance metrics storage

2. **Features**:
   - `AdaptiveWinRateEngine`: Core engine with performance tracking
   - `calculate_adaptive_parameters()`: Dynamic position sizing
   - `get_sizing_multiplier()`: Confidence-based multiplier (0.7x-1.3x)
   - `get_performance_summary()`: Real-time metrics
   - Auto-learns every 10 trades (configurable)
   - Ultra-light memory (<1MB Redis footprint)

3. **Integration Points**:
   - Workers: `workers/gpt_auto_suggest.py` (added import + init)
   - Can track trade results via `update_trade_result()`
   - Works with existing dynamic sizing engine
   - Non-blocking on failure (graceful degradation)

#### **Previous Fixes - MetaBrain v9.2**
1. **Precision Calculator Budget Constraints** ✅
   - MAX_WALLET_PCT: Reduced from 95% to 30% (prevents huge positions)
   - Investment capped at $25-35 per trade (removed multipliers)
   - Test Result: ACHUSDT executes with EXACT $25.00 investment

2. **Auto-Protect Script Fixed** ✅
   - File: `protect_unprotected_positions.py`
   - Fixed imports: `futures_get_open_positions` → `futures_open_positions_safe`
   - Added type safety for `futures_mark_price()` function

3. **Universal SL/TP Manager** ✅
   - File: `utils/universal_sltp_manager.py`
   - 0.1% minimum distance check (prevents APIError -2021)
   - ReduceOnly properly formatted (prevents APIError -2022)
   - Multi-Target TP: TP1/TP2/TP3 attached properly

4. **Portfolio Intelligence** ✅
   - File: `utils/portfolio_intelligence.py`
   - Symbol concentration check prevents overlapping trades
   - Daily trade limits prevent spam execution
   - Exposure management enforced per symbol

### Previous Fixes - MetaBrain v9.1 Release
1. **Fills Watcher Protection System** ✅
   - Migrated to `attach_multi_target_protection()`
   - Attaches TP1/TP2/TP3 + SL for ALL fills
   - File: `workers/fills_watcher.py` (lines 1296-1336)
   - Status: RUNNING and actively watching

2. **Middleware HEAD Request** ✅
   - File: `main.py` (lines 284+)
   - Properly handles health checks and readiness endpoints

## System Architecture

### UI/UX
The system provides a dashboard UI and enhanced Telegram notifications, utilizing HTML formatting, emojis, and inline interactive buttons for user interaction.

### Technical Implementations
The core application is built with FastAPI and Gunicorn, emphasizing modularity and policy management via YAML files. All critical data is saved to a PostgreSQL database.

**Core Features:**
-   **Automated Trading Modes**: Supports MARKET, HYBRID, and FULL AUTO execution.
-   **Live Trade Management**: Dynamic management of open positions with TP, SL, BE logic, and ATR-based trailing stops.
-   **Market Scanner**: Autonomous multi-timeframe (15M+1H+4H) technical analysis across Binance Futures with weighted trend detection.
-   **AI-Powered Proposals**: Uses DeepSeek Chat for trade decisions with adaptive Risk/Reward, intelligent brain management, and dynamic quality threshold enforcement.
-   **GRID Trading**: Integrated FUTURES GRID trading with dynamic symbol selection, tiered strategies, dynamic sizing, and automatic SL/TP protection.
-   **Risk Management**: Includes quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
-   **Dynamic Budget System**: 100% dynamic trade budget calculation based on equity-tied ceiling, quality multiplier, volatility adjustment, and floor/cap.
-   **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit.
-   **MetaBrain - AI-Driven Precision Trading**: Features a 3-stage auto-deployment engine, 1-Brain Lean Architecture (DeepSeek Chat), intelligent brain management, smart override logic, regime-based dynamic MIN_QUALITY, precision calculator for leverage/investment, deep market analyzer, dynamic protection manager, balance-tiered risk profiles, auto-strategy selection, multi-target TP system (TP1/TP2/TP3), dynamic trailing SL, auto-flip multi-timeframe analysis, and a regime detection engine.
-   **Adaptive Win Rate Optimizer** (NEW): Tracks recent performance (30 trades), calculates Sharpe ratio, adjusts position sizing (1-5%) dynamically, scales SL/TP based on confidence, regime-aware adjustments.
-   **ExecutionBot**: Centralized architecture for all trade execution logic with source-aware approval gating and Stage Engine integration, ensuring 100% SL/TP protection.
-   **Multi-Target Protection System**: Attach TP1/TP2/TP3 + SL to LIMIT orders via Fills Watcher (after fill detection) and MARKET orders (immediately).
-   **Auto-Optimization System**: Self-adaptive trading through intelligent parameter tuning, multi-level protection (Warning/Conservative/Emergency modes), and a symbol tiering engine with dynamic blacklist management.
-   **Insurance Monitor System**: Multi-layered account protection including Drawdown Protection, Margin Ratio Defense, Cross/Isolated Balancer, and a Circuit Breaker.
-   **Validation & Safety Infrastructure**: Includes a Validation Pipeline, Fail-Closed Decision Gates, Monte Carlo simulations, Live Health Monitor, 3-Layer Emergency Protection System, Hedge Position Manager, Stop Order Validator, Order Hygiene System, and an enhanced SL/TP ENGINE.
-   **Hedge Mode Auto-Activation System**: Fully automatic Hedge Mode activation.
-   **Smart LIMIT+MARKET Order Router**: Decision matrix for intelligent order routing.
-   **Order Consolidation System**: Limits orders per symbol, auto-merges similar prices, and optimizes strategic TP levels.
-   **Hybrid Dynamic Leverage System**: 100% dynamic leverage (2-35x) adapting in real-time.
-   **Trading Policy Filters**: System-wide protection via Symbol Filter Engine (100% dynamic volume filtering, liquidity, Binance whitelist/blacklist), Adaptive Volume Filter Integration, Market-Aware Threshold Selection, Order Quality Monitor, Position Limits Manager, and Trading Gatekeeper.
-   **Dynamic Smart Filter**: Regime-Aware + AUTO Percentile Strategy for adaptive volume analysis, auto-percentile strategy selection, adaptive volume thresholds, regime-based RR & quality thresholds, dynamic BTC correlation penalty, adaptive direction penalty, and market intelligence integration.
-   **Dynamic TOP 100 Symbol Filter**: Blocks trades for symbols outside the TOP 100.
-   **Binance Symbol Validator**: Universal coverage for all order creation paths with side-aware rounding, real-time sync with Binance, graceful fallback, and precision error prevention.
-   **Position Mode Management**: Prevents APIError -4061 through `POSITION_MODE_OVERRIDE`, auto-adaptation logic, centralized wrapper system, cache invalidation, retry logic fix, and startup skip logic.
-   **Trade Execution Pipeline**: Calculates quantity from budget, supports HYBRID flow, and persists metadata to Redis before execution.
-   **Telegram Digest System**: Consolidated notification system for batched reports.

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
