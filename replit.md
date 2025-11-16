# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous algorithmic trading platform designed for 24/7 Binance Futures trading. It leverages AI, specifically DeepSeek Chat, to scan 534 symbols and make intelligent trade decisions. The platform integrates 7 trading strategies, dynamic capital management, and aims for 4-10 high-quality daily trades. Its MetaBrain v9.1 eliminates hardcoded logic, with all trade parameters determined by AI analysis. The system features intelligent brain management with auto-suspend/resume for failed providers and is built for scalability and autonomous operation with a self-adaptive engine and complete data persistence.

### Recent Bug Fixes (Nov 16, 2025)

**System Optimization & Cost Reduction (Nov 16, 2025):**
- **TOP 50 Pre-Filter** (NEW FEATURE): Auto Scanner now filters symbol pool by TOP 50 list BEFORE expensive AI calls, reducing wasted resources. Fail-open design (requires ≥10 matches) prevents over-filtering. Logged as "TOP 50 Pre-Filter" with symbol counts.
- **MIN_QUALITY_FLOOR Optimization**: Lowered from 6.0 to 4.0 to enable trades in CHOPPY markets while maintaining safety. Quality scores 3.0 and below rejected, 4.0+ approved. Balanced approach between safety and opportunity.
- **Blacklist Cleanup**: Cleared 47 stale failure counters and temp blacklist entries from Redis, restoring full symbol trading capability. Zero Tolerance now requires 5 failures before 24h ban (less aggressive than previous 3-failure threshold).
- **Trade Success**: 1000FLOKIUSDT GRID trade executed successfully after fixes, proving end-to-end system functionality with TOP 50 compliance.
- **Coverage Status**: Quantum Worker producing 47 TOP 50 symbols (target: 50-160). Auto Scanner pool shows 8/50 symbols matching TOP 47, triggering fail-open mode for broader market coverage.

**Previous Enhancements (Nov 15, 2025):**
- **Dynamic Penalty System** (MAJOR UPGRADE): Converted rigid blocking to intelligent penalty scoring. Counter-trend trades get -1.5 penalty, with-trend trades get +0.5 bonus. System now allows reversals but penalizes low-quality counter-trends, preventing 100% blocking while maintaining safety.
- **BTC Correlation Check** (NEW FEATURE): Stage 4 filter checks if altcoin trades align with BTC market direction. BTC bullish + LONG altcoin = +0.5 bonus, BTC bearish + LONG altcoin = -1.0 penalty. Respects that most altcoins follow BTC's lead.
- **Expanded Symbol Scanning** (OPTIMIZATION): Increased candidate pool from 120 to 160 symbols (100 previous TOP 100 + 60 random). Better coverage for finding high-quality trading opportunities.
- **Directional Bias**: Updated AI prompts with explicit SHORT/LONG guidance based on EMA alignment. System now proposes SHORT trades in bearish markets, LONG in bullish markets, both in neutral.
- **Regime Detection**: Added bb_width_pct, ema20_slope, ema50_slope indicators to _fetch_real_indicators. Regime detection now accurate with complete technical data.

**Previous Fixes:**
- **Type Safety**: Fixed all 11 LSP errors with proper type annotations, import time checks, and None value guards in execution_bot.py
- **Liquidity Check**: TOP 50 symbols now bypass liquidity checks (proven liquid), others validated with 100-level depth check
- **Budget Validation**: Fixed GRID budget validation to use notional amount (budget × leverage) instead of raw budget
- **Redis Cleanup**: Implemented proper blacklist cleanup preventing false positives from stale failure counters
- **First Trade Success**: LTCUSDT GRID trade executed successfully with Telegram notification and Redis persistence

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
-   **AI-Powered Proposals**: Uses DeepSeek Chat for trade decisions with adaptive Risk/Reward, intelligent brain management, and dynamic quality threshold enforcement. **Dynamic Quality Scoring (Nov 2025)**: Quality scores (6-10 range) calculated in real-time from Market Intelligence multi-factor analysis (momentum, volatility, liquidity, technical patterns) - no hardcoded values.
-   **GRID Trading (Nov 2025)**: Integrated FUTURES GRID trading with dynamic symbol selection, tiered strategies, **Dynamic Sizing Engine** ($25-150 budget before leverage, 1-35x leverage), and **automatic SL/TP protection** for all GRID fills via Fills Watcher. ExecutionBot stores GRID metadata to Redis (24h TTL), Fills Watcher detects fills and adds ATR-based SL/TP immediately.
-   **Risk Management**: Includes quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
-   **Dynamic Budget System v2.0**: Real-time trade budget calculation ($25-$150 per trade) based on available wallet balance, trade quality, and volatility. Auto-adapts to available margin with ON DEMAND mode - fast polling (10s) when margin < $25, immediate resume when funds freed. Default: 50% of available balance per trade, scaled by quality score (5-9). Uses withdrawAvailable ($70) instead of availableBalance ($0.17) for accurate free cash reading.
-   **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit.
-   **Complete Data Persistence**: All critical data is saved to a PostgreSQL database.

**MetaBrain v9.1 - AI-Driven Precision Trading:**
-   **1-Brain Lean Architecture**: DeepSeek Chat for autonomous trade decisions, with optional expansion brains (Qwen 2.5 Turbo, Gemini 2 Pro, Claude Sonnet, Grok) for multi-brain consensus.
-   **Intelligent Brain Management**: Auto-suspends/resumes failed AI providers, dynamic consensus thresholds, cost tracking, and token budgeting.
-   **Precision Calculator v1.0**: Calculates exact leverage and investment based on trade quality, market volatility, regime, and balance.
-   **Deep Market Analyzer & Live Regime Detector**: Multi-layer technical analysis and real-time market classification (TRENDING, CHOPPY, VOLATILE, SIDEWAYS).
-   **Dynamic Protection Manager**: AI suggests regime-specific parameter sets with guardrails.

**ExecutionBot - Unified Trade Execution Wrapper:**
-   Centralized architecture for all trade execution logic.
-   Source-aware approval gating and dual flow support (MARKET and HYBRID).
-   **100% SL/TP Protection (Nov 2025)**: ALL positions receive automatic Stop Loss and Take Profit orders **immediately** after entry. ATR-based SL with 2% fallback, RR-based TP with 3% fallback. If SL/TP placement fails, position is emergency-closed automatically - NO unprotected positions allowed.

**Auto-Optimization System (Self-Adaptive Trading):**
-   **Intelligent Parameter Tuning**: Analyzes performance and adjusts `min_quality`, RR, and leverage based on win rate.
-   **Multi-Level Protection**: Activates Warning/Conservative/Emergency modes based on performance.
-   **Symbol Tiering Engine & Dynamic Blacklist Manager**: Classifies symbols by performance and auto-blacklists underperforming ones.

**Trailing TP System:**
-   Auto-activates at 25-30% profit and dynamically adjusts trailing distance to secure profits.

**Insurance Monitor System (Account Protection):**
-   Multi-layered protection including Drawdown Protection, Margin Ratio Defense, Cross/Isolated Balancer, and a Circuit Breaker.

**Validation & Safety Infrastructure:**
-   Includes a Validation Pipeline, Fail-Closed Decision Gates, Monte Carlo simulations, Live Health Monitor, and a 3-Layer Emergency Protection System (pre-trade, post-entry, continuous monitoring).
-   Advanced Risk Manager with dynamic ATR-based SL, 60-second hold with 2% max loss cap, and breakeven acceleration.
-   Entry Timestamps Persistence: Redis for primary storage with PostgreSQL backup for disaster recovery.

**Smart LIMIT+MARKET Order Router:**
-   Decision matrix based on ATR%, spread, signal age, urgency, book depth, and breakout detection to route orders intelligently. Supports LIMIT, MARKET, and HYBRID modes.

**Order Consolidation System:**
-   Limits orders per symbol, auto-merges similar prices, and optimizes strategic TP levels with minimum distance enforcement.

**Hybrid Dynamic Leverage System v2.0:**
-   100% dynamic leverage (2-35x) adapting in real-time based on market conditions, trade quality, and multi-factor confidence scoring.
-   Includes 3-Layer Safety Guards, Market Regime Detection, Symbol Tier System, Recovery Mode, Portfolio Protection, Dynamic Position Sizing, and Time-Based Protection.

**Trading Policy Filters (System-Wide Protection):**
-   **Symbol Filter Engine**: Validates symbols based on volume, liquidity, Binance whitelist, and blacklist management. TOP 50 symbols bypass liquidity checks (proven liquid), others validated with 100-level order book depth.
-   **Order Quality Monitor**: Tracks fill rate, slippage, and execution speed.
-   **Position Limits Manager**: Sets max positions per symbol, total open orders, and correlation exposure limits.
-   **Trading Gatekeeper**: Unified pre-trade validation integrating all filters and Dynamic Leverage.
-   **Zero Tolerance Filter**: Auto-cleanup for expired temp blacklist entries; requires 5 failures before 24h ban (less aggressive than previous 3-failure threshold). Clean separation between TOP 50 validation and liquidity validation.

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
-   **Redis Cloud**: High-performance caching and temporary data storage ($6/month paid subscription, 30MB storage, SSL disabled for compatibility).