# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous algorithmic trading platform for 24/7 Binance Futures trading. It scans 534 symbols, making AI-powered trade decisions using DeepSeek Chat. The platform integrates 7 trading strategies with dynamic capital management, aiming for 4-10 high-quality daily trades. Its MetaBrain v9.1 eliminates hardcoded logic, with all trade parameters determined by AI analysis. The system features intelligent brain management with auto-suspend/resume for failed providers and is designed for scalability. It operates autonomously, supported by a self-adaptive engine and complete data persistence.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations.

## System Architecture

### UI/UX
The system features a dashboard UI and enhanced Telegram notifications, utilizing HTML formatting, emojis, and inline interactive buttons for improved user experience.

### Technical Implementations
The core application is built with FastAPI and Gunicorn, emphasizing modularity and policy management via YAML files.

**Core Features:**
-   **Automated Trading Modes**: Supports MARKET, HYBRID, and FULL AUTO execution.
-   **Live Trade Management**: Dynamic management of open positions with TP, SL, BE logic, and ATR-based trailing stops.
-   **Market Scanner**: Autonomous worker performs multi-timeframe technical analysis across Binance Futures markets.
-   **AI-Powered Proposals**: Utilizes DeepSeek Chat for trade decisions with adaptive Risk/Reward thresholds and intelligent brain management.
-   **GRID Trading**: Integrated FUTURES GRID trading.
-   **Risk Management**: Implements quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
-   **Dynamic Budget System**: Real-time trade budget calculation based on account equity, trade quality, volatility, and defined floors/ceilings.
-   **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit.
-   **Complete Data Persistence**: All critical data is saved to a PostgreSQL database.

**MetaBrain v9.1 - AI-Driven Precision Trading:**
-   **1-Brain Lean Architecture**: Uses DeepSeek Chat for autonomous trade decisions with significant cost reduction.
-   **Intelligent Brain Management System**: Auto-suspends/resumes failed AI providers and scales to multi-brain consensus with dynamic consensus thresholds, cost tracking, and token budgeting.
-   **Optional Expansion Brains**: Qwen 2.5 Turbo, Gemini 2 Pro, Claude Sonnet, Grok can be activated for multi-brain consensus.
-   **Dynamic Quality Threshold Enforcement (v9.2)**: Hard override mechanism ensures trades meeting dynamic `min_quality` thresholds are approved.
-   **Precision Calculator v1.0**: Calculates exact leverage and investment amounts based on trade quality, market volatility, regime, and balance.
-   **Deep Market Analyzer**: Multi-layer technical analysis covering trend, volatility, support/resistance, market structure, and volume.
-   **Live Regime Detector**: Real-time market classification (TRENDING, CHOPPY, VOLATILE, SIDEWAYS) using ADX, ATR, Bollinger Bands, and price range.
-   **Dynamic Protection Manager**: AI suggests regime-specific parameter sets with guardrails from `order_sanity.py`, `leverage_policy.py`, `precision_calculator.py`.

**ExecutionBot - Unified Trade Execution Wrapper:**
-   **Centralized Architecture**: All trade execution logic consolidated into `utils/execution_bot.py`.
-   **Source-Aware Approval Gating**: Intelligent bypass for already-approved sources and automation flows.
-   **Dual Flow Support**: MARKET flow (budget-only) and HYBRID flow (custom TP/SL) with automatic fallback.

### AI Brains System
The system integrates a scalable multi-brain architecture with intelligent management:
-   **Active Brain**: DeepSeek Chat for deep market analysis.
-   **Suspended Brains (Ready for Activation)**: Qwen 2.5 Turbo, Gemini 2 Pro, Claude Sonnet, Grok.
-   **Brain Management Features**: Auto-suspend/resume, dynamic consensus, cost tracking, scalable architecture, token budgeting.

**Auto-Optimization System (Self-Adaptive Trading):**
-   **Intelligent Parameter Tuning**: Analyzes performance and automatically adjusts `min_quality`, RR, and leverage based on win rate.
-   **Multi-Level Protection**: Activates Warning/Conservative/Emergency modes based on win rate, consecutive losses, and daily PnL.
-   **Symbol Tiering Engine**: Classifies symbols as Tier A/B/C based on performance, with auto promotion/demotion.
-   **Dynamic Blacklist Manager**: Auto-blacklists symbols with 3+ consecutive losses.

**🎯 Trailing TP System (Profit Protection):**
-   **Auto-Activation**: Activates when position reaches 25-30% profit threshold.
-   **Dynamic Trailing**: Continuously monitors peak prices and adjusts trailing distance to secure profits.

**🛡️ Insurance Monitor System (Account Protection):**
-   **Layer 1 - Drawdown Protection**: Stops new opens and closes positions if daily PnL drops below a threshold.
-   **Layer 2 - Margin Ratio Defense**: Closes losing positions if Cross Margin Ratio drops too low.
-   **Layer 3 - Cross/Isolated Balancer**: Alerts on imbalanced margin.
-   **Layer 4 - Funding Rate Killer**: Monitors funding rates (future feature).
-   **Layer 5 - Circuit Breaker**: Closes all positions and suspends trading if total account PnL drops significantly.

### Validation & Safety Infrastructure
Includes a Validation Pipeline (backtesting), Fail-Closed Decision Gates, Data-Driven Monte Carlo simulations, a Live Health Monitor, and Circuit Breakers.

**🛡️ Emergency Protection System (3-Layer Defense):**
-   **Layer 1 - Pre-Trade Validation**: Every trade requires SL+TP configuration.
-   **Layer 2 - Post-Entry Verification**: Verifies SL/TP orders on Binance; missing orders trigger emergency close.
-   **Layer 3 - Continuous Monitoring**: Checks for unprotected positions; if detected, triggers immediate market close.

**🛡️ Advanced Risk Manager (3-Layer Loss Prevention):**
-   **Layer 1 - Dynamic SL (ATR-Based)**: Automatically calculates and places stop-loss orders based on market volatility.
-   **Layer 2 - 60-Second Hold + 2% Max Loss Cap**: Enforces minimum hold period and hard 2% maximum loss cap with entry timestamp persistence.
-   **Layer 3 - Breakeven Acceleration**: Moves SL to breakeven when position reaches +0.5% profit.

**💾 Entry Timestamps Persistence (Redis + Database):**
-   **Redis Primary Storage**: Sub-millisecond entry timestamp retrieval with 1-hour TTL auto-cleanup.
-   **Database Backup**: Automatic backup to PostgreSQL every 5 minutes for disaster recovery.
-   **Restart-Proof**: Entry times survive system restarts via recovery logic on startup.
-   **Dual Storage**: Prevents 60-second hold bypass during high-frequency restarts.

**📍 Smart LIMIT+MARKET Order Router:**
-   **Decision Matrix**: ATR%, spread, signal age, urgency, book depth, breakout detection.
-   **Intelligent Routing**: LIMIT for low volatility (sniper precision), MARKET for high volatility (urgent execution).
-   **HYBRID Mode**: Medium volatility with LIMIT → MARKET escalation after 60s.
-   **Purpose-Aware**: Optimizes for ENTRY, EXIT, TP, SL, GRID based on context.

**🔧 Order Consolidation System:**
-   **Max 4 Orders Per Symbol**: Prevents order book clutter and API rate limits.
-   **Auto-Merge Similar Prices**: Consolidates orders within 0.3% price range.
-   **Strategic TP Optimization**: Keeps 3 strategic levels (closest, middle, furthest).
-   **Minimum Distance Enforcement**: 1% spacing between TP levels for risk management.

**🚀 Hybrid Dynamic Leverage System v2.0:**
-   **100% Dynamic Leverage (2-35x)**: Adapts in real-time based on market conditions and trade quality.
-   **Multi-Factor Confidence Scoring**: Quality (30%), Market Regime (25%), Symbol Tier (20%), Win Rate (15%), Volatility (10%).
-   **3-Layer Safety Guards**: Emergency Brake (Win Rate<30% = 5x max), Volatility Guard (ATR>5% = 10x max), Symbol Protection (Blacklist = 0x).
-   **Market Regime Detection**: TRENDING (25-35x), VOLATILE (15-25x), CHOPPY (8-15x), CRASH (3-8x).
-   **Symbol Tier System**: Tier A (Win Rate >60%), Tier B (45-60%), Tier C (30-45%), Tier D/Blacklist (<30%).
-   **Recovery Mode**: After large losses, gradual leverage increase 5x → 8x → 12x → 15x → 20x → 25x → 30x.
-   **Portfolio Protection**: Max 30% total exposure, correlation limits reduce leverage by 30-40%.
-   **Dynamic Position Sizing**: Leverage >25x = 1% position, >15x = 2%, ≤15x = 3-5% (confidence-based).
-   **Time-Based Protection**: Night hours (22-06) = 15x max, Weekend = 10x max, Economic events = 8x max.
-   **Auto-Blacklist**: 3 consecutive losses = 30-day automatic blacklist.
-   **Real-Time Performance Tracking**: Win rate, consecutive losses, daily PnL per symbol.
-   **Seamless Fallback**: If disabled or fails, falls back to static leverage_policy.py.

**🔍 Trading Policy Filters (System-Wide Protection):**
-   **Symbol Filter Engine**: Validates symbols before trading based on 24H volume ($10M+ default), liquidity depth ($50k+ order book), TOP 70 Binance symbols whitelist, blacklist management.
-   **Order Quality Monitor**: Tracks fill rate (65%+ required), slippage monitoring (2% max average), execution speed metrics, automatic poor-performing symbol flagging.
-   **Position Limits Manager**: Max 2 positions per symbol, max 25 total open orders, correlation exposure limits (30% max to correlated groups), single symbol exposure cap (15% max portfolio).
-   **Trading Gatekeeper**: Unified pre-trade validation gate integrating all filters + Dynamic Leverage. Every trade must pass: Symbol validation → Quality check → Position limits → Leverage calculation before execution.
-   **Fail-Open Architecture**: If filters fail to load, system allows trades (prevents false blocks), all filters log warnings for debugging.
-   **Integration**: Wired into `allow_and_fix_ticket` in risk_guard.py - every trade validated before execution.

### Telegram Digest System
Consolidated notification system with batched reports for Health, Trade/PnL, Critical Alerts, and AI Trade Reviews.

### Deployment Architecture
The production environment runs on Render.com with 11 Background Workers and a Neon PostgreSQL database, connected to GitHub for auto-deployment. Replit is used for development.

**Infrastructure Notes:**
- **Redis:** Upstash Redis with External URL (`rediss://square-hawk-37108.upstash.io`) - accessible from Replit + Render
- **Database:** Neon PostgreSQL with Scale-to-Zero (Free tier) - endpoint auto-suspends after 5 minutes of inactivity and auto-resumes on first query
- **Critical Tables:** breaker_state, trades, proposals, market_states, app_heartbeat, guardian_fixes
- **Known Issues Fixed:** 
  - Redis Internal URL replaced with Upstash External URL (Nov 2025)
  - N8N_WEBHOOK_SECRET added to prevent production startup failures (Nov 2025)
  - Database Scale-to-Zero behavior documented (endpoint resumes automatically on query)

## External Dependencies

-   **Binance Futures API**: Market data, order execution, account management.
-   **Neon PostgreSQL**: Persistent data storage.
-   **DeepSeek API**: AI provider for trade optimization and consensus voting.
-   **Alibaba Cloud DashScope API**: Qwen 2.5 Turbo for fast AI reasoning.
-   **Google Gemini API**: Gemini 2 Pro for fast multi-modal reasoning.
-   **Anthropic Claude API**: Claude Sonnet 3.5 for consensus validation.
-   **AI-X/Grok API**: Optional fallback AI provider.
-   **Telegram Bot API**: Notifications, approval workflows, interactive callbacks.
-   **N8N Workflow Automation**: External workflow integration, news ingestion.
-   **Gunicorn**: Production-grade WSGI HTTP server.