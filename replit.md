# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is a comprehensive algorithmic trading platform built with FastAPI and Python, designed for 24/7 live Binance Futures trading. It features automated market scanning (530+ symbols), AI-powered trade decisions via GPT-4, GRID trading options, and professional automated dynamic management. The platform aims for 4-10 high-quality trades per day with significant profits and minimal losses, ultimately targeting a fully self-adaptive trading engine with dynamic capital optimization and complete data persistence.

**Latest Update (Nov 1, 2025):**
- ✅ **Multi-Timeframe Analysis FIXED** - Resolved all NoneType comparison errors in market_intelligence.py, system now analyzes 15M/1H/4H data without errors (enable via `USE_MULTI_TF=1`)
- ✅ **Production-Ready** - Comprehensive DEPLOYMENT.md guide created for render.com deployment
- ✅ Dynamic Sizing Engine fully integrated - calculates leverage (2-10x) and position size (10-60% equity) based on trade quality, RR, AI confidence, and market conditions
- ✅ Market Intelligence enhanced - saves all market states to PostgreSQL for historical analysis
- ✅ CHOPPY market strategy fixed - now uses GRID trading (MinRR=1.30) instead of wait mode (MinRR=1.70)
- ✅ Resource Manager added - smart Memory/CPU monitoring with async batch processing
- ✅ Database persistence verified - all system decisions auto-save to PostgreSQL

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations.

## System Architecture

### UI/UX
A dashboard UI is located in `static/dashboard/`. Telegram notifications are enhanced with rich HTML formatting, emojis, and inline interactive buttons for a better user experience, providing visual tagging for different trade types (e.g., 🔷 GRID Trade vs ⚡ Regular Trade).

### Technical Implementations
The core application is built with FastAPI (`main.py`) and uses Gunicorn for serving. Key functionalities are modularized into `routes/` for API endpoints and `utils/` for common functions. Policies are managed via YAML files in `policies/`.

**Core Features:**
- **Automated Trading Modes**: Supports MARKET, HYBRID, and AUTO execution modes.
- **Live Trade Management**: Dynamic management of open positions with Take Profit (TP), Stop Loss (SL), Break-Even (BE) logic, and ATR-based trailing stops with freeze logic and spike detection.
- **Market Scanner**: An autonomous worker performs multi-timeframe technical analysis (15M/1H/4H) every 60 seconds across 531 Binance Futures markets.
- **AI-Powered Proposals**: OpenAI GPT-4 analyzes market data and generates trade proposals with mandatory Risk/Reward (RR) ≥ 1.3. Proposals with RR < 1.2 or unrealistic success_pct (outside 35%-95% range) are rejected.
- **GRID Trading**: Integrated FUTURES GRID trading for choppy/sideways markets.
- **Risk Management**: Implements strict quality filters, dynamic filters based on market mood/regime, liquidity checks, cooldown periods, deduplication, daily trade caps, and a circuit breaker for daily loss limits.
- **Telegram Approval Workflow**: Trade proposals are sent to Telegram with interactive approval buttons.
- **Dynamic Position Management**: Features ATR Trailing (freeze logic, spike detection), Multi-level TP ladder, and Dynamic Position Sizing (equity%, quality, volatility).
- **Auto-Flip**: The system dynamically adapts to market conditions, proposing LONG or SHORT trades based on real-time analysis, with a multi-system validation process for reversals.
- **Self-Adaptive Trading Engine**: Incorporates Market Intelligence (regime, mood, volatility detection), Adaptive AI Prompts (regime-specific instructions), and Portfolio Intelligence (exposure management, position limits, correlation prevention).
- **Dynamic Capital Optimization**: Automatically calculates leverage (2-10x) and position sizing based on trade quality, RR, AI confidence, and market conditions.
- **Complete Data Persistence**: All critical data, including trade sizing, position flips, market states, performance records, and system decisions, is automatically saved to a PostgreSQL database for audit, analysis, and system learning.

**Security & Authentication:**
- Uses Bearer Token (`X-API-Key`) and HMAC Signature for secure access.
- Includes anti-replay protection and mandatory Telegram approval for trade execution.

## External Dependencies

-   **Binance Futures API**: For market data, order execution, and account management.
-   **OpenAI API**: For AI-powered trade proposal generation and market analysis.
-   **Telegram Bot API**: For notifications, approval workflows, and interactive callbacks.
-   **Gunicorn**: Production-grade WSGI HTTP server.
-   **PostgreSQL**: For persistent data storage.
-   **SQLAlchemy**: ORM for database interaction.
-   **Psycopg2**: PostgreSQL adapter for Python.
-   **psutil**: System and process monitoring for resource management.

## Recent Changes (November 2025)

**Nov 1 - CRITICAL BUG FIXES (Multi-Timeframe Analysis):**
1. **NoneType Errors Fixed**: Resolved all TypeError exceptions in `utils/market_intelligence.py` where None values were being compared with integers/floats
2. **Methods Fixed**: `_detect_regime`, `_classify_mood`, `_classify_volatility`, `_calculate_trend_strength`, `_calculate_confidence`
3. **Solution**: Implemented explicit None checking pattern to preserve legitimate zero values:
   ```python
   value = ctx.get("key")
   if value is None:
       value = default
   ```
   This ensures ADX=0 (no trend) stays 0 instead of becoming 20 (weak trend), preserving accurate market analysis
4. **Verification**: System now running without errors, Multi-TF analysis fully functional, zero values correctly preserved
5. **Deployment Guide**: Created comprehensive DEPLOYMENT.md for render.com production deployment

**Nov 1 - Multi-Timeframe Analysis:**
1. **MultiTFContextManager**: Smart caching system with tiered TTLs (30s/120s/300s) for 15M/1H/4H data to prevent redundant API calls
2. **/context/batch Enhanced**: Extended API to support multi-TF requests via optional `intervals` parameter while maintaining backward compatibility
3. **Market Intelligence Upgrade**: Added `analyze_multi_tf()` method with TF alignment detection (STRONG/MODERATE/WEAK/CONFLICTING) and cross-timeframe trend confirmation
4. **Auto Scanner Integration**: Worker now requests and analyzes multi-TF data when `USE_MULTI_TF=1` is set, falling back gracefully to single-TF mode
5. **Debug Logging**: Added comprehensive BAD SIG debug logging to Telegram callbacks for signature mismatch diagnostics

**Nov 1 - GRID Trading Full Integration:**
1. **GRID Proposals Working End-to-End**: Fixed async bugs and added full GRID support to /alerts/ingest endpoint
2. **Telegram GRID Notifications**: GRID proposals now appear in Telegram with 🔷 icon, range, levels, and budget details
3. **Portfolio Validation for GRID**: GRID proposals pass through portfolio intelligence checks before submission
4. **Database Persistence**: All GRID decisions auto-save to PostgreSQL for historical analysis
5. **Verified Live**: System generating 2+ GRID proposals per cycle in CHOPPY market conditions

**Earlier (Nov 1) - Dynamic Integration & CHOPPY Fix:**
1. **Dynamic Sizing Integration**: Connected DynamicSizingEngine to Auto Scanner - system now calculates optimal leverage and position size for every trade proposal
2. **Market Intelligence Enhancement**: Fixed symbol tracking to enable proper database persistence of market states
3. **CHOPPY Market Bug Fix**: Changed strategy from wait (MinRR=1.70, almost no trades) to grid (MinRR=1.30, active trading) for sideways markets
4. **Resource Management**: Added ResourceManager with async batch processing and Memory/CPU monitoring
5. **Database Verification**: Confirmed auto-save working - market_states table recording all market analysis decisions

**Database Tables Active:**
- `market_states` - Real-time market regime/mood/strategy decisions (growing)
- `trade_sizing` - Calculated leverage/position sizes for all proposals
- `position_flips` - LONG↔SHORT flip decisions tracking
- `performance_records` - Trade performance metrics
- `system_decisions` - All major system decisions for audit trail