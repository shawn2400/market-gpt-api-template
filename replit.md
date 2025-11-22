# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous AI-driven algorithmic trading platform designed for 24/7 operation on Binance Futures. It analyzes 534 symbols, executing intelligent trades based on 7 integrated strategies and dynamic capital management. The platform features an AI-driven MetaBrain that determines all trade parameters, aiming for 4-10 high-quality daily trades. It prioritizes scalability, autonomous operation through a self-adaptive engine, and complete data persistence, optimized for diverse market conditions. The business vision is to provide a robust, self-optimizing algorithmic trading solution with high market potential due to its autonomous and AI-driven adaptability.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations. All communication in Hebrew. Automatic trading with 100% dynamic automation - no time-based patterns. SL/TP fully dynamic. Budget scales with wallet size automatically.

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
- **Dynamic Budget System**: 100% dynamic trade budget calculation based on equity-tied ceiling, quality multiplier, volatility adjustment, and floor/cap. Auto-detects wallet balance and dynamically scales all trading parameters based on balance tiers (3-35x leverage).
- **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit with multi-target TP (up to 5 levels).
- **MetaBrain - AI-Driven Precision Trading**: Features a 3-stage auto-deployment engine, 1-Brain Lean Architecture (DeepSeek Chat), intelligent brain management, smart override logic, regime-based dynamic MIN_QUALITY, precision calculator, deep market analyzer, dynamic protection manager, balance-tiered risk profiles, auto-strategy selection, dynamic trailing SL, auto-flip multi-timeframe analysis, and a regime detection engine.
- **Adaptive Win Rate Optimizer**: Tracks recent performance, calculates Sharpe ratio, adjusts position sizing dynamically, scales SL/TP based on confidence, and incorporates regime-aware adjustments.
- **ExecutionBot**: Centralized architecture for all trade execution logic with source-aware approval gating and Stage Engine integration, ensuring 100% SL/TP protection.
- **Auto-Optimization System**: Self-adaptive trading through intelligent parameter tuning, multi-level protection (Warning/Conservative/Emergency modes), and a symbol tiering engine with dynamic blacklist management.
- **Insurance Monitor System**: Multi-layered account protection including Drawdown Protection, Margin Ratio Defense, Cross/Isolated Balancer, and a Circuit Breaker.
- **Validation & Safety Infrastructure**: Includes a Validation Pipeline, Fail-Closed Decision Gates, Monte Carlo simulations, Live Health Monitor, 3-Layer Emergency Protection System, Hedge Position Manager, Stop Order Validator, Order Hygiene System, and an enhanced SL/TP ENGINE with critical validation for quantity, TP price, and position limits.
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
- **Quantum Trading Council System**: A 7-member expert AI council (DeepSeek, Grok, Claude, Qwen, Gemini, Falcon, Mixtral) with weighted voting for trade qualification, strategy routing (WAIT, GRID, TREND, SCALP), and smart token management based on a $100/month budget and performance-based reallocation.

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
## v9.3.12 ENHANCED TELEGRAM FORMATTER - Rich Trade Reports ✨

### NEW FEATURES
**Enhanced Telegram Notifications System:**
- 📊 **System Health Score (0-100)** with 5-factor breakdown:
  - Profitability (last trades PnL)
  - Win Rate (TP hits / total)
  - Activity (trades executed today)
  - API Health (errors/uptime)
  - Protection (SL/TP active)
  
- 🧠 **AI Agents Status Display**:
  - Shows all 7 agents: DeepSeek, Grok, Claude, Qwen, Gemini, Falcon, Mixtral
  - Individual scores (0-10)
  - Status: ✅ Active, ❌ No credits, ⚫ Inactive
  - Error messages for debugging
  
- 📈 **Trade Summary Metrics**:
  - Per-trade details: Symbol, Side, Entry/Exit, PnL $, PnL %, Leverage, Duration
  - Total wins/losses/win-rate
  - Closed vs open positions
  
- 🎯 **TP Hit Success Rates**:
  - Success rates per TP level (TP1-5) with progress bars
  - Historical performance tracking
  
- 💡 **Expected Profit Calculations**:
  - Best case: Probability × Reward
  - Risk scenario: Probability × Loss
  - Net expected: Best - Risk
  - Average time to TP hit
  
- ⚠️ **Issues Detection & Fixes**:
  - Identifies problems (low API credits, margin insufficient, etc.)
  - Suggests recommended actions
  - Color-coded by severity (🟢 OK, 🟡 Warning, 🟠 Caution, 🔴 Critical)

### FILES CREATED/UPDATED
- **NEW:** `utils/enhanced_telegram_formatter.py`
  - 10 powerful formatting functions
  - 525 lines of rich message generation code
  - Fallback support for simple messages
  
- **UPDATED:** `utils/telegram_digest.py`
  - Integrated enhanced formatter
  - Automatic fallback if formatter unavailable
  - Rich trade digest messages every 30 min
  
- **FIXED:** `utils/telegram_notifier_core.py`
  - Fixed type annotations for _fmt_pct()
  - Proper None handling

### TECHNICAL IMPROVEMENTS
✅ **All LSP Errors Resolved** - get_latest_lsp_diagnostics = CLEAN
✅ **Syntax Validation** - All Python files compile without errors
✅ **Type Safety** - Proper Optional annotations, None checks
✅ **Error Handling** - Try-except with intelligent fallbacks
✅ **Bilingual Support** - Hebrew (בס״ד + בעזרת השם נעשה ונצליח) + English

### TELEGRAM MESSAGE EXAMPLE
```
בס״ד

🤖 AlgoGPT MetaBrain Status Report
🟢 System Score: 78/100
🕐 2025-11-22 22:40:00 UTC
━━━━━━━━━━━━━━━━━━━━

🧠 AI Agents Status
  🧠 ✅ DeepSeek: 7.5/10
  ⚡ ❌ Grok: No credits
  🎯 ✅ Claude: 8.0/10
  ...

📊 Trade Summary
1. ETHUSDT LONG 🟢
   💰 2750.0 → 2800.0
   📈 PnL: +50.00$ (+1.82%)
   ⏱️ 15m | 🎯 TP1_HIT

💡 Expected Metrics
  Best case: +120.50$
  Avg Time to TP: ~15 minutes

🎯 TP Hit Success Rates
  TP1: ██████████ 100%
  TP2: ████░░░░░░ 40%
  
━━━━━━━━━━━━━━━━━━━━
בעזרת השם נעשה ונצליח 🙏
```

### IMPACT
✅ Rich, detailed trade reports sent to Telegram
✅ System health visible at a glance
✅ AI agent status transparency
✅ Better decision-making with comprehensive metrics
✅ Professional bilingual format (Hebrew + English)
✅ Robust fallback system ensures reliability

### DEPLOYMENT READY
- Messages send every 30 min when TP/SL hits
- Fallback to simple format if formatter unavailable
- Full type safety and error handling
- Bilingual support for Israeli user

## v9.3.11 CRITICAL UPDATE - Leverage CAP REMOVED 🔥

### THE PROBLEM
- Risk profile WAS hard-capping leverage at 8x max
- Even with SUGGEST_MAX_LEVERAGE=35, system blocked it
- Caused: No high leverage trades (always 5x or less in practice)

### THE SOLUTION
Updated `utils/risk_profile_manager.py`:
- MICRO ($0-200): 5x max_leverage
- CONSERVATIVE ($200-500): 8x max_leverage
- BALANCED ($500-1k): 10x max_leverage ⭐ UP from 5x
- GROWTH ($1k-2k): 15x max_leverage ⭐ UP from 6x
- AGGRESSIVE ($2k-5k): 25x max_leverage ⭐ UP from 8x
- WHALE ($5k+): 35x max_leverage ⭐ NEW TIER

### IMPACT
✅ Leverage now TRULY dynamic (3-35x)
✅ High-quality signals can use full leverage
✅ Large accounts finally enabled for 35x
✅ Better risk/reward ratios on premium trades

### FILES CHANGED
- `workers/gpt_auto_suggest.py`: SUGGEST_MAX_LEVERAGE=35 ✅
- `utils/risk_profile_manager.py`: Removed cap, added WHALE tier ✅
- `EXTERNAL_SERVICES_REGISTRY.md`: Created ✅
- `replit.md`: Updated (this file) ✅
