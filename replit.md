# AlgoGPT - Algorithmic Trading Platform (MetaBrain v8.0)

## Overview
AlgoGPT is an algorithmic trading platform for 24/7 live Binance Futures trading, built with FastAPI and Python. It automates market scanning across 530+ symbols, utilizes AI-powered trade decisions via GPT-5 and multi-AI consensus, and includes GRID trading options and dynamic capital management. The platform aims for 4-10 high-quality daily trades, focusing on profitability, minimal losses, and a self-adaptive trading engine with complete data persistence.

**MetaBrain v8.0** introduces fully autonomous regime-driven trading with 3-layer database resilience for production stability on Render.com.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations.

## System Architecture

### UI/UX
The system includes a dashboard UI (`static/dashboard/`) and enhanced Telegram notifications with HTML formatting, emojis, and inline interactive buttons for improved user experience.

### Technical Implementations
The core application uses FastAPI and Gunicorn, with modularized functionalities in `routes/` for API endpoints and `utils/` for common functions. Policies are managed via YAML files.

**Core Features:**
-   **Automated Trading Modes**: Supports MARKET, HYBRID, and FULL AUTO execution.
-   **Live Trade Management**: Dynamic management of open positions with TP, SL, BE logic, and ATR-based trailing stops.
-   **Market Scanner**: Autonomous worker performs multi-timeframe technical analysis across 531 Binance Futures markets.
-   **AI-Powered Proposals**: Utilizes 5 AI providers (GPT-5, Gemini 2 Pro, DeepSeek, Grok, Claude) for consensus-based trade decisions with adaptive Risk/Reward thresholds based on market regime.
-   **GRID Trading**: Integrated FUTURES GRID trading for choppy/sideways markets.
-   **Mean-Reversion Strategy**: Deterministic VWAP-based strategy for choppy/neutral markets using real Binance OHLCV data.
-   **Scalping & Range-Bounce Strategies**: Aggressive short-term strategies for choppy markets.
-   **Risk Management**: Implements quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker.
-   **Dynamic Budget System**: Trade budgets are calculated in real-time based on account equity, trade quality, volatility, and defined floors/ceilings.
-   **Dynamic SL/TP Calculation**: Stop Loss is ATR-based, and Take Profit is RR-based, adapting to market volatility and regime.
-   **Complete Data Persistence**: All critical data is saved to a PostgreSQL database.

**MetaBrain v8.0 Features:**
-   **Database Resilience (3-Layer Protection)**: 
    - Auto-pause prevention in Neon Console
    - Exponential backoff retries with wake-up handling
    - Fallback queue to JSON when DB offline + periodic resync
-   **Dynamic Regime System**: 
    - 4 market regimes: TRENDING, CHOPPY, VOLATILE, SIDEWAYS
    - Context-adaptive strategy switching (Breakout for trends, Grid for chop, Mean-reversion for sideways)
    - Regime-specific SL/TP multipliers and trailing logic
-   **Zero-Gap SL Manager**: Place new SL → Verify → Cancel old SL (never leaves position unprotected)
-   **TP Ladder System**: Multi-level take profits (TP1-TP4) with configurable weights (50%/30%/20%)
-   **Daily Trading Reports**: Comprehensive Telegram reports with PnL, Win Rate, Best/Worst trades

**Security & Authentication:**
-   Uses Bearer Token (`X-API-Key`) and HMAC Signature, with anti-replay protection and mandatory Telegram approval.

### AI Brains System (MetaBrain v7.5)
The system integrates 9+ specialized AI systems with 5 AI providers for consensus-based decisions:
-   **Multi-AI Consensus Engine**: OpenAI GPT-5 (orchestrator), Google Gemini 2 Pro (fast reasoning), DeepSeek Chat (parameter optimization), AI-X Grok (health monitoring), and Claude Sonnet 3.5 (optional validation).
-   **Specialized AI Systems**: GPT Auto Suggest, Multi-AI Consensus Scorer, Adaptive Prompt Engine, Market Intelligence Brain, Portfolio Intelligence, News Sentiment Analyzer, and Auto-Flip System.

### Validation & Safety Infrastructure (v2.0)
Includes a Validation Pipeline (backtesting), Fail-Closed Decision Gates (Dual Confirmation), Data-Driven Monte Carlo simulations, a Live Health Monitor, and Circuit Breakers.

### Deployment Architecture
The production environment runs on Render.com with 8 background workers and a Neon PostgreSQL database (ep-cool-tooth-a5dlnc71), connected to GitHub for auto-deployment. Replit is used solely for development and testing, with a separate development database. The system is platform-agnostic and does not rely on Replit-specific features for production.

**MetaBrain v8.0 Production Requirements:**
- Neon Database: Auto-pause DISABLED in console (prevents trade failures)
- Database Resilience: 3-layer protection enabled (backoff retries + fallback queue)
- Dynamic Regime System: FORCE_REGIME="" (auto-detection enabled)
- Capital: $166 USDT for 5-6 simultaneous positions
- Dependencies: psycopg[binary]>=3.2.1 for PostgreSQL 3.x support

### Progressive Rollout - Dynamic Regime Trading (v8.0+)

MetaBrain v8.0 introduces **100% dynamic, context-adaptive position management** with confidence-based regime detection and adaptive parameter mixing. The system uses a **3-phase Progressive Rollout** strategy for safe deployment:

**Key Features:**
- **Regime Detection v2**: Confidence-based classification (TRENDING/CHOPPY/VOLATILE/SIDEWAYS) with minimum 62% confidence threshold
- **Adaptive Parameter Mixing**: Context-aware SL/TP calculation based on regime, volatility, PnL state, and position age
- **Zero-Gap SL Updates**: Places new SL → Verifies → Cancels old SL (never leaves positions unprotected)
- **TP Ladder System**: Multi-level take profits with dynamic distribution
- **Safety Guards**: Stale data protection (35s max age), low confidence filter, BTC correlation gate, circuit breaker (5 failures → 15min cooldown)
- **Idempotency Protection**: HMAC-based duplicate order prevention (90s window)
- **Prometheus Metrics**: Full observability with decisions, skips, errors, SL/TP changes, guard triggers

**3-Phase Deployment Strategy:**

**Phase 1: Shadow Mode (48-72 hours)**
- Configuration:
  ```
  MANAGER_DYN_PATH=1
  DYN_SHADOW=1
  DYN_ENFORCE=0
  DYN_ALLOWED_SYMBOLS=
  ```
- Behavior: Calculates SL/TP dynamically but **does not execute** - logs only
- Purpose: Validate regime detection, parameter calculations, and safety guards
- Validation Checkpoints:
  - ✅ Regime detection confidence >62% for most symbols
  - ✅ SL/TP calculations are reasonable (SL 1.5-2.5 ATR, TP RR 1.5-3.0x)
  - ✅ No excessive skips due to stale data or low confidence
  - ✅ Circuit breaker not triggering falsely
- Logs: Search for `evt:dyn_shadow` in Fills Watcher logs

**Phase 2: Single Symbol Enforce (48-72 hours)**
- Configuration:
  ```
  MANAGER_DYN_PATH=1
  DYN_SHADOW=0
  DYN_ENFORCE=1
  DYN_ALLOWED_SYMBOLS=ADAUSDT
  ```
- Behavior: **Executes** dynamic SL/TP updates **only for ADAUSDT**
- Purpose: Test live execution on a single, controlled symbol
- Validation Checkpoints:
  - ✅ Zero-Gap SL updates execute successfully (no gaps in protection)
  - ✅ TP Ladder placements work correctly
  - ✅ No order failures or rejections
  - ✅ Metrics confirm successful SL/TP changes
  - ✅ Position management improves vs. legacy (fewer premature stops, better RR)
- Logs: Search for `DynPath ENFORCE` in Fills Watcher logs

**Phase 3: Full Production**
- Configuration:
  ```
  MANAGER_DYN_PATH=1
  DYN_SHADOW=0
  DYN_ENFORCE=1
  DYN_ALLOWED_SYMBOLS=
  ```
- Behavior: **Executes** dynamic SL/TP updates **for all symbols**
- Purpose: Full autonomous position management across all positions
- Validation Checkpoints:
  - ✅ System handles multiple simultaneous positions (5-6 positions)
  - ✅ No performance degradation or excessive API calls
  - ✅ Win rate and RR metrics improve vs. baseline
  - ✅ Circuit breaker protects against cascading failures

**Current Status (as of Nov 6, 2025):**

🎉 **System is in Phase 3 - Full Production**
- ✅ Configuration: `MANAGER_DYN_PATH=1`, `DYN_SHADOW=0`, `DYN_ENFORCE=1`, `DYN_ALLOWED_SYMBOLS=` (all symbols)
- ✅ APIError -1106 FIXED: Smart reduceOnly handling for Hedge Mode (never sends reduceOnly when positionSide present)
- ✅ Dynamic SL/TP Updates: Operational on all symbols
- ✅ Regime Detection: Active (CHOPPY detected with 65.7-69.7% confidence on BNBUSDT)
- ✅ Zero-Gap SL Manager: Successfully updating stop losses without gaps
- ✅ TP Ladder System: Multi-level take profits working (TP1/TP2 placed correctly)
- ✅ Safety Guards: All operational (stale data guard, low conf filter, BTC gate, circuit breaker)
- ✅ Idempotency: Duplicate order prevention active
- ✅ Recent Successful Update: BNBUSDT SHORT position managed (SL=962.89, TP=[956.22, 953.66])

**Recent Fixes (Nov 6, 2025):**
- Fixed Binance Hedge Mode compatibility: `reduceOnly` parameter is now automatically removed when `positionSide` is present
- Logic in `utils/binance_client.py::futures_create_order` ensures compliance with Binance API requirements
- All position management (SL + TP) now executes without -1106 errors

**Instant Rollback Procedure:**

If issues are detected at any phase:
1. Set `MANAGER_DYN_PATH=0` in ENV to **immediately** disable dynamic path
2. Restart Fills Watcher workflow
3. System falls back to legacy position management instantly
4. Monitor `/metrics` endpoint for `algogpt_dyn_enforce` gauge (should be 0)
5. Review logs and metrics to identify root cause

**Monitoring & Metrics:**

- **Endpoint**: `GET /metrics` (Prometheus exposition format)
- **Key Metrics**:
  - `algogpt_dyn_decisions_total{symbol,regime}` - Decision counter by symbol/regime
  - `algogpt_dyn_skips_total{reason}` - Skip reasons (stale_data, low_conf, circuit_block, etc.)
  - `algogpt_dyn_errors_total{stage}` - Error counter by stage
  - `algogpt_sl_changes_total{symbol}` - Successful SL updates
  - `algogpt_tp_sets_total{symbol}` - Successful TP ladder placements
  - `algogpt_stale_guard_hits_total` - Stale data protection triggers
  - `algogpt_low_conf_hits_total` - Low confidence guard triggers
  - `algogpt_circuit_blocks_total` - Circuit breaker blocks
  - `algogpt_dyn_enforce` - 1 if enforce mode active, 0 if shadow/disabled
  - `algogpt_regime_confidence{symbol,regime}` - Current regime confidence by symbol

**Implementation Files:**
- `utils/trade_manager.py` - Main integration (manages open positions)
- `utils/regime_detector_v2.py` - Confidence-based regime classification
- `utils/adaptive_mixer.py` - Context-aware parameter calculation
- `utils/precision.py` - Binance tick/step size quantization
- `utils/idempotency_simple.py` - Duplicate order prevention
- `utils/circuit_breaker.py` - Failure protection with exponential cooldown
- `utils/metrics_dyn.py` - Prometheus metrics definitions
- `utils/sl_manager.py` - Zero-Gap SL replacement (legacy)
- `utils/tp_ladder.py` - Multi-level TP placement (legacy)

## External Dependencies

-   **Binance Futures API**: Market data, order execution, account management.
-   **OpenAI API**: GPT-5 for AI trade proposals and market analysis.
-   **Google Gemini API**: Gemini 2 Pro for fast multi-modal reasoning.
-   **DeepSeek API**: AI provider for trade optimization.
-   **AI-X/Grok API**: AI provider for system supervision.
-   **Anthropic Claude API** (optional): Claude Sonnet 3.5 for consensus validation.
-   **Telegram Bot API**: Notifications, approval workflows, interactive callbacks.
-   **N8N Workflow Automation**: External workflow integration, news ingestion.
-   **Gunicorn**: Production-grade WSGI HTTP server.
-   **PostgreSQL**: Persistent data storage.
-   **SQLAlchemy**: ORM for database interaction.
-   **Psycopg2**: PostgreSQL adapter.
-   **psutil**: System and process monitoring.
-   **httpx**: Async HTTP client for AI provider API calls.
-   **scipy**: Scientific computing for statistical analysis.
-   **numpy**: Numerical computing for simulations and metrics.