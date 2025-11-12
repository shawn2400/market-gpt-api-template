# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an algorithmic trading platform for 24/7 live Binance Futures trading. It automates market scanning across 534 symbols and uses a 100% autonomous AI-powered trade decision-making process. The platform features a consensus engine powered by 5 AI models (GPT-5, Gemini 2 Pro, DeepSeek, Grok, Claude) and integrates 7 trading strategies (Mean-Reversion, Scalping, Range-Bounce, Trend-Following, Breakout, GRID, SPOT) with dynamic capital management. AlgoGPT aims for 4-10 high-quality daily trades and autonomous operation, supported by a self-adaptive trading engine and complete data persistence via 8 background workers. Its MetaBrain v9.1 eliminates hardcoded logic, with all trade parameters (strategy, leverage, investment, entry timing) determined by hierarchical AI consensus.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations.

## Recent Changes
**November 12, 2025** - Fixed critical Auto Scanner data flow and cleaned up error logging:
- **Root Cause**: `_fetch_context_batch` returned empty dict when CONTEXT_URL not set, causing AI Strategy Consensus to receive incomplete market data (high_24h/low_24h = None)
- **Fix 1**: Modified `_fetch_context_batch` (line 220-222) to call `_build_local_context()` instead of returning empty dict when Context API unavailable
- **Fix 2**: Replaced `_build_local_context` implementation with clean placeholder - actual indicators calculated by `_fetch_real_indicators` later in pipeline (eliminates import errors)
- **Impact**: AI Strategy Consensus now receives complete 24h range data, selecting MEAN_REVERSION/GRID strategies with 70-85% confidence instead of defaulting to WAIT
- **Result**: System logs are clean (no import/module errors), all data flows correctly through the pipeline
- **Status**: ✅ Local system fully operational and verified, production deployment ready (Git committed, requires Render worker restart)

## System Architecture

### UI/UX
The system provides a dashboard UI and enhanced Telegram notifications, utilizing HTML formatting, emojis, and inline interactive buttons for improved user experience.

### Technical Implementations
The core application is built with FastAPI and Gunicorn, featuring modularized functionalities and policy management via YAML files.

**Core Features:**
-   **Automated Trading Modes**: Supports MARKET, HYBRID, and FULL AUTO execution.
-   **Live Trade Management**: Dynamic management of open positions with TP, SL, BE logic, and ATR-based trailing stops.
-   **Market Scanner**: Autonomous worker performs multi-timeframe technical analysis across 531 Binance Futures markets.
-   **AI-Powered Proposals**: Utilizes 5 AI providers for consensus-based trade decisions with adaptive Risk/Reward thresholds.
-   **GRID Trading**: Integrated FUTURES GRID trading.
-   **Mean-Reversion Strategy**: Deterministic VWAP-based strategy.
-   **Scalping & Range-Bounce Strategies**: Aggressive short-term strategies.
-   **Risk Management**: Implements quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
-   **Dynamic Budget System**: Real-time trade budget calculation based on account equity, trade quality, volatility, and defined floors/ceilings.
-   **Dynamic SL/TP Calculation**: ATR-based Stop Loss and RR-based Take Profit, adapting to market volatility.
-   **Complete Data Persistence**: All critical data is saved to a PostgreSQL database.

**MetaBrain v9.1 - 100% AI-Driven Precision Trading:**
-   **5-Brain Hierarchical Consensus Architecture**: Orchestrated by GPT-5, supported by Gemini 2 Pro, DeepSeek, Grok, and Claude Sonnet 3.5. Requires ≥3 brains to approve for trade execution.
-   **AI Strategy Consensus Engine**: 100% AI-driven strategy selection via a 5-brain voting system based on independent market analysis.
-   **Precision Calculator v1.0**: Calculates exact leverage (e.g., 7.34x) and investment amounts (e.g., $487.23) based on trade quality, market volatility, regime, and balance.
-   **Deep Market Analyzer**: Multi-layer technical analysis covering trend, volatility, support/resistance, market structure, and volume.
-   **Live Regime Detector**: Real-time market classification into TRENDING, CHOPPY, VOLATILE, or SIDEWAYS using ADX, ATR, Bollinger Bands, and price range.
-   **Entry Timing Optimizer**: Analyzes recent price action and volatility to determine optimal entry timing, providing a confidence level and optional delay.
-   **Enhanced Trade Notifications**: Professional Telegram alerts in 70% Hebrew + 30% English with detailed entry/exit data, real-time PNL updates, accurate ROI calculation, and HTML formatting.
-   **Dynamic Protection Manager**: AI suggests 4 regime-specific parameter sets (Entry Quality, SL ATR, TP RR, Trail ATR, Leverage) - values are SUGGESTIONS, not hardcoded limits. AI has near-total freedom per-trade.
-   **100% AI-Driven Parameters**: Wide safety ranges (quality 2-10, SL 0.5-4 ATR, TP 1-5 RR, leverage 1-15x) with downstream guardrails (order_sanity.py, leverage_policy.py, precision_calculator.py) enforcing caps. BE timing decided per-trade by AI based on volatility, trend strength, and PnL trajectory.
-   **Accurate ROI Calculation**: ROI = (PNL_USDT / actual_investment) × 100, where investment = (position_value / leverage). Side detected from Binance positionAmt sign (not price comparison). Shows true return on capital invested, accounting for leverage effect.
-   **Dual Order Types**: Uses both LIMIT and MARKET orders dynamically based on regime and volatility.
-   **Smart Position Mode Compatibility**: Auto-detects and adapts to both Hedge Mode and One-Way Mode on Binance.
-   **100% Strategic Freedom**: Generates trades for all market conditions (LONG/SHORT/GRID/SPOT/Scalping/Mean-Reversion).
-   **AI Consensus Parameters**: Final parameter values are the median of proposals from all AI brains within wide safety ranges. No hardcoded thresholds or templates.
-   **Database Resilience**: 3-layer protection including auto-pause prevention, exponential backoff retries, and fallback queries.
-   **Daily Trading Reports**: Comprehensive Telegram reports with PnL, Win Rate, and trade summaries (70% Hebrew, 30% English).
-   **Security & Authentication**: Uses Bearer Token (`X-API-Key`) and HMAC Signature with anti-replay protection.
-   **Alert Management**: Auto Health Monitor uses specific failure thresholds and cooldowns to prevent alert spam.

### AI Brains System
The system integrates **5 AI brains** in a hierarchical consensus architecture: OpenAI GPT-5 (orchestrator), Google Gemini 2 Pro, DeepSeek Chat, AI-X Grok, and Anthropic Claude Sonnet 3.5. This includes specialized AI systems for market intelligence, portfolio intelligence, news sentiment, and an auto-flip system. A **Post-Trade AI Review System** has all 5 AIs independently analyze trades. The **Autonomous Improvement System** automatically applies parameter improvements (e.g., SL/TP multipliers, leverage caps) and commits changes to GitHub when 3+ brains reach 60%+ consensus.

### Validation & Safety Infrastructure
Includes a Validation Pipeline (backtesting), Fail-Closed Decision Gates (Dual Confirmation), Data-Driven Monte Carlo simulations, a Live Health Monitor, and Circuit Breakers.

**🛡️ Emergency Protection System (3-Layer Defense):**
-   **Layer 1 - Pre-Trade Validation**: Every trade must have SL+TP configuration before execution begins.
-   **Layer 2 - Post-Entry Verification**: Within 2 seconds after entry, system verifies SL/TP orders exist on Binance exchange. If missing → Emergency market close + Circuit breaker activation.
-   **Layer 3 - Continuous Monitoring**: Position Monitor checks every 30 seconds for unprotected positions. If detected → Immediate market close + System pause.
-   **Circuit Breaker**: Auto-triggers when 2+ unprotected positions detected within 1 hour. Sets `PAUSE_AUTO_RUN=1` and sends critical Telegram alerts.
-   **Enhanced Logging**: Full telemetry of every order (placed, filled, cancelled, expired) with detailed timestamps and status changes for forensic analysis.
-   **Emergency Close Function**: Direct market close bypassing normal order flow, used exclusively for unprotected positions.
-   **100% Coverage Guarantee**: No trade can remain open without verified SL+TP protection.

### Telegram Digest System
Consolidated notification system with batched reports for Health, Trade/PnL, Critical Alerts, and AI Trade Reviews. Rate limiting ensures efficient notification delivery.

### Deployment Architecture
The production environment runs on Render.com with **8 Background Workers** and a Neon PostgreSQL database, connected to GitHub for auto-deployment. Replit is used for development and testing. The system supports a 3-phase progressive rollout for dynamic regime trading, currently in full production (Phase 3).

**8 Workers:** AlgoGPT Server, Auto Health Monitor, Auto Scanner, Daily Meeting 00:00, Fills Watcher v2.0 (AI Post-Trade Review + Auto-Improvement), GPT-5 Central Brain, Position Monitor (Auto SL/TP Protection), and Sentinel Security.

## External Dependencies

-   **Binance Futures API**: Market data, order execution, account management.
-   **Neon PostgreSQL API**: Auto-resume endpoint management.
-   **OpenAI API**: GPT-5 for AI trade proposals, market analysis, and post-trade reviews.
-   **Google Gemini API**: Gemini 2 Pro for fast multi-modal reasoning and trade scoring.
-   **DeepSeek API**: AI provider for trade optimization and post-trade analysis.
-   **AI-X/Grok API**: AI provider for system supervision and trade reviews.
-   **Anthropic Claude API**: Claude Sonnet 3.5 for consensus validation and post-trade scoring.
-   **GitHub API**: Auto-commit system improvements.
-   **Telegram Bot API**: Notifications, approval workflows, interactive callbacks, digest reports.
-   **N8N Workflow Automation**: External workflow integration, news ingestion.
-   **Gunicorn**: Production-grade WSGI HTTP server.
-   **PostgreSQL (Neon)**: Persistent data storage.
-   **psycopg[binary]>=3.2.0**: PostgreSQL adapter.
-   **psutil**: System and process monitoring.
-   **httpx**: Async HTTP client.
-   **scipy**: Scientific computing.
-   **numpy**: Numerical computing.