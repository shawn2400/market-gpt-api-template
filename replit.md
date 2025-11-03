# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is a comprehensive algorithmic trading platform built with FastAPI and Python, designed for 24/7 live Binance Futures trading. It features automated market scanning (530+ symbols), AI-powered trade decisions via GPT-5, multi-AI consensus, GRID trading options, and professional automated dynamic management. The platform aims for 4-10 high-quality trades per day with significant profits and minimal losses, ultimately targeting a fully self-adaptive trading engine with dynamic capital optimization and complete data persistence.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations.

## System Architecture

### UI/UX
A dashboard UI is located in `static/dashboard/`. Telegram notifications are enhanced with rich HTML formatting, emojis, and inline interactive buttons for a better user experience, providing visual tagging for different trade types (e.g., 🔷 GRID Trade vs ⚡ Regular Trade).

### Technical Implementations
The core application is built with FastAPI (`main.py`) and uses Gunicorn for serving. Key functionalities are modularized into `routes/` for API endpoints and `utils/` for common functions. Policies are managed via YAML files in `policies/`.

**Core Features:**
-   **Automated Trading Modes**: Supports MARKET, HYBRID, and AUTO execution modes.
-   **Live Trade Management**: Dynamic management of open positions with Take Profit (TP), Stop Loss (SL), Break-Even (BE) logic, and ATR-based trailing stops with freeze logic and spike detection.
-   **Market Scanner**: An autonomous worker performs multi-timeframe technical analysis (15M/1H/4H) every 60 seconds across 531 Binance Futures markets.
-   **AI-Powered Proposals**: OpenAI GPT-5 analyzes market data and generates trade proposals with mandatory Risk/Reward (RR) ≥ 1.3. Multi-AI consensus available via DeepSeek and AI-X/Grok for enhanced decision quality.
-   **GRID Trading**: Integrated FUTURES GRID trading for choppy/sideways markets.
-   **Risk Management**: Implements strict quality filters, dynamic filters based on market mood/regime, liquidity checks, cooldown periods, deduplication, daily trade caps, and a circuit breaker for daily loss limits.
-   **Telegram Approval Workflow**: Trade proposals are sent to Telegram with interactive approval buttons.
-   **Dynamic Position Management**: Features ATR Trailing (freeze logic, spike detection), Multi-level TP ladder, and Dynamic Position Sizing (equity%, quality, volatility).
-   **Auto-Flip**: The system dynamically adapts to market conditions, proposing LONG or SHORT trades based on real-time analysis, with a multi-system validation process for reversals.
-   **Self-Adaptive Trading Engine**: Incorporates Market Intelligence (regime, mood, volatility detection), Adaptive AI Prompts (regime-specific instructions), and Portfolio Intelligence (exposure management, position limits, correlation prevention).
-   **Dynamic Capital Optimization**: Automatically calculates leverage (2-10x) and position sizing based on trade quality, RR, AI confidence, and market conditions.
-   **Complete Data Persistence**: All critical data, including trade sizing, position flips, market states, performance records, and system decisions, is automatically saved to a PostgreSQL database for audit, analysis, and system learning.

**Security & Authentication:**
-   Uses Bearer Token (`X-API-Key`) and HMAC Signature for secure access.
-   Includes anti-replay protection and mandatory Telegram approval for trade execution.

## External Dependencies

-   **Binance Futures API**: For market data, order execution, and account management.
-   **OpenAI API**: GPT-5 model (gpt-5-2025-08-07) via SDK 2.6.1 for AI-powered trade proposal generation and market analysis.
-   **DeepSeek API**: Alternative AI provider for multi-AI consensus scoring.
-   **AI-X/Grok API**: Third AI provider for consensus-based decision making.
-   **Telegram Bot API**: For notifications, approval workflows, and interactive callbacks.
-   **N8N Workflow Automation**: For external workflow integration, news ingestion, and incident management.
-   **Gunicorn**: Production-grade WSGI HTTP server.
-   **PostgreSQL**: For persistent data storage.
-   **SQLAlchemy**: ORM for database interaction.
-   **Psycopg2**: PostgreSQL adapter for Python.
-   **psutil**: System and process monitoring for resource management.
-   **httpx**: Async HTTP client for AI provider API calls.
-   **scipy**: Scientific computing library for Student-t distributions and statistical analysis.
-   **numpy**: Numerical computing for Monte Carlo simulations and metrics.

## Validation & Safety Infrastructure (v2.0)

**NEW in Ultimate Edition v2.0:** Production-grade validation and safety systems based on 8+ AI consultations.

### Components:
-   **Validation Pipeline** - Historical backtesting with walk-forward testing (6 folds), per-regime analysis
-   **Fail-Closed Decision Gates** - Dual Confirmation (Quant ∧ AI ∧ Risk) with no permissive fallbacks
-   **Data-Driven Monte Carlo** - Student-t/Bootstrap distributions (NOT Gaussian) for realistic SL/TP probabilities
-   **Live Health Monitor** - Win% 7d/30d, Drawdown tracking, Consecutive loss counter
-   **Circuit Breakers** - Daily DD limits (5%), Consecutive SL limits (4), Volatility gates, Emergency stop

### API Endpoints:
```
POST /validate/run         - Start backtest validation
GET  /validate/status?id=X - Check backtest status
GET  /validate/report?id=X - Get validation report

GET  /monitors/health      - System health status
POST /monitors/breaker/pause  - Manual circuit breaker trigger
POST /monitors/breaker/reset  - Reset circuit breaker
GET  /monitors/breaker/status - Detailed breaker status

GET  /ai/leaderboard       - AI model performance leaderboard
GET  /ai/performance       - Individual model performance metrics
WS   /ws/pnl               - Real-time P&L WebSocket updates
```

### Environment Variables (Production Safety):
```bash
# Validation Controls
VALIDATION_REQUIRED=1          # Require backtest validation before production
DUAL_CONFIRM_ENABLE=1          # Enable fail-closed dual-gate confirmation
MC_DIST_SOURCE=student_t       # Monte Carlo distribution (student_t/bootstrap/garch)

# Circuit Breaker Settings
BREAKER_DD_LIMIT_PCT=5.0       # Daily drawdown limit (%)
BREAKER_CONSEC_SL_MAX=4        # Max consecutive stop losses
BREAKER_VOLATILITY_THRESHOLD=50 # Volatility spike threshold (%)

# Database
USE_DB=1                       # Enable database persistence
DATABASE_URL=sqlite:////app/data/algogpt.db  # Database path

# Backtest Thresholds
MIN_WINRATE_PCT=46             # Minimum winrate for validation pass
MIN_RR=1.45                    # Minimum Risk/Reward ratio
MAX_DRAWDOWN_PCT=12            # Maximum drawdown tolerance
```

## Production Enhancements (Phase 1) - COMPLETED Nov 2025

**NEW:** Production-grade infrastructure and AI performance tracking.

### AI Performance Tracking:
-   **Dynamic Model Weighting** - AI models weighted by recent Win% per market regime (7d/30d)
-   **Prediction Logging** - All AI predictions logged to database (ai_predictions table)
-   **Outcome Tracking** - Trade outcomes tracked and linked to predictions (trade_outcomes table)
-   **Feedback Dataset** - Labeled dataset for future fine-tuning (feedback_dataset table)
-   **AI Leaderboard Dashboard** - Real-time performance metrics via Tab 20 in dashboard

### Database Hardening:
-   **Slippage History** - Migrated from JSON to PostgreSQL with proper indexes
-   **Circuit Breaker State** - Persistent in DB (breaker_state table), survives restarts
-   **Market States** - Market intelligence data persisted (market_states table)
-   **Audit Logging** - Complete action logging for compliance (audit_log table)

### Enhanced Monitoring & Security:
-   **Real-time P&L** - WebSocket /ws/pnl with 10-second updates
-   **Tiered Alerting** - INFO/WARNING/CRITICAL/EMERGENCY levels via Telegram
-   **Rate Limiting** - 60 requests/min/IP protection against abuse
-   **Log Masking** - Sensitive data (API keys, amounts) automatically masked
-   **Comprehensive Testing** - Full test suite with smoke tests, load tests, memory profiling

### Performance Metrics:
-   **Memory Usage**: 0.76GB peak (50% below 1.5GB target)
-   **9/9 Workflows**: All running error-free
-   **Response Times**: <100ms for most endpoints
-   **Database Tables**: 10 core tables with proper indexes