# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is a comprehensive algorithmic trading platform built with FastAPI and Python, designed for **24/7 live Binance Futures trading** with automated market scanning (530+ symbols), AI-powered trade decisions via GPT-4, GRID trading options (FUTURES GRID), and professional automated dynamic management. Target: 4-10 high-quality trades per day with large profits and minimal losses.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations.

## System Architecture

### Backend
The core application is built with FastAPI (`main.py`) and uses Gunicorn for serving. Key functionalities are modularized into `routes/` (for API endpoints like context, alerts, and Telegram callbacks) and `utils/` (for common functions like HMAC, authentication, and trade execution). Policies are managed via YAML files in `policies/`.

### Key Features
- **Automated Trading Modes**: Supports MARKET, HYBRID, and AUTO execution modes.
- **Live Trade Management**: Dynamic management of open positions with Take Profit (TP), Stop Loss (SL), Break-Even (BE) logic, and ATR-based trailing stops with freeze logic and spike detection.
- **Market Scanner**: An autonomous worker (`workers/gpt_auto_suggest.py`) performs multi-timeframe technical analysis every 60 seconds across 531 Binance Futures markets.
- **AI-Powered Proposals**: OpenAI GPT-4 analyzes market data and generates trade proposals with mandatory RR≥1.3 (TARGET ≥1.5-2.0).
- **AI Response Validation**: Early rejection of proposals with RR<1.2 or unrealistic success_pct (outside 35%-95% range).
- **GRID Trading**: Integrated FUTURES GRID trading for choppy/sideways markets (routes/grid.py, utils/grid_manager.py, utils/grid_executor.py).
- **Risk Management**: Implements strict quality filters, dynamic filters based on market mood/regime, liquidity checks, cooldown periods, deduplication, and daily trade caps.
- **Telegram Approval Workflow**: Trade proposals sent to Telegram with rich HTML formatting, visual tagging (🔷 GRID Trade vs ⚡ Regular Trade), and interactive approval buttons.
- **Dynamic Position Management**: ATR Trailing (freeze logic, spike detection), Multi-level TP ladder, Dynamic Position Sizing (equity%, quality, volatility), MARKET order precision.
- **Auto-Flip**: The system dynamically adapts to market conditions, proposing LONG or SHORT trades based on real-time analysis.

### UI/UX
A dashboard UI is located in `static/dashboard/`. Telegram notifications are enhanced with rich HTML formatting, emojis, and inline interactive buttons for a better user experience.

### Technical Implementations
- **Authentication**: Uses Bearer Token (`X-API-Key`) and HMAC Signature for secure access and critical operations.
- **Security**: Includes anti-replay protection, strict quality filters, multi-layer risk management, and mandatory Telegram approval for trade execution.
- **Advanced Features**:
  - ATR Trailing Stop with freeze logic, spike detection, ADX-based adjustments
  - Multi-level TP ladder (tp1/tp2/tp3) with configurable splits (40%-35%-25%)
  - Dynamic Position Sizing based on equity percentage, quality multiplier, and volatility multiplier
  - MARKET Order precision handling with minNotional protection and overshoot guards

## Recent Changes (November 1, 2025)

### Phase 1: Foundation (Completed)
1. **Enhanced AI Prompt**: Changed from weak "Favor RR≥1.6" to mandatory "RR≥1.3 MINIMUM, TARGET ≥1.5-2.0" with concrete examples.
2. **AI Response Validation**: Added early rejection of proposals with RR<1.2 or unrealistic success_pct.
3. **GRID Trading Integration**: Connected grid_builder.py, grid_manager.py, and routes/grid.py to main.py; enabled SUGGEST_GRID=1 in Auto Scanner.
4. **Telegram Visual Tagging**: Added 🔷 GRID Trade vs ⚡ Futures/Spot Trade labels in approval messages.
5. **Validated Existing Infrastructure**: Confirmed ATR Trailing, Multi-TP, Position Sizing, and MARKET Orders are all implemented and working.

### Phase 2: Self-Adaptive Trading Engine (NEW - November 1, 2025)

**🧠 Market Intelligence Engine (`utils/market_intelligence.py`)**
- **Market Regime Detection**: Automatically classifies markets as Trending/Sideways/Choppy/Volatile using ADX, ATR, and Bollinger Bands
- **Market Mood Analysis**: Identifies Bullish/Bearish/Neutral conditions using EMAs, MACD, and RSI
- **Volatility Classification**: Categorizes volatility as High/Medium/Low based on ATR percentage
- **Trend Strength Scoring**: 0-100 score indicating trend clarity and confidence
- **Adaptive Thresholds**: Dynamic min_rr and quality thresholds that adjust based on market conditions

**📝 Adaptive AI Prompts (`utils/adaptive_prompts.py`)**
- **Regime-Specific Prompts**: Different AI instructions for each market condition
  - Trending Bullish → Aggressive long setups, breakouts
  - Trending Bearish → Aggressive short setups, breakdowns
  - Sideways → GRID trading recommendations
  - Choppy → Ultra-selective, high-quality only
  - Volatile → Wait or extreme caution
- **Dynamic RR Requirements**: Higher RR required in uncertain markets, lower in strong trends
- **Strategy Optimization**: AI tailored to extract maximum profit from each regime

**🛡️ Portfolio Intelligence (`utils/portfolio_intelligence.py`)**
- **Exposure Management**: Prevents over-exposure with configurable limits
  - Max total exposure: 80% of account equity (default)
  - Max LONG exposure: 60% of equity
  - Max SHORT exposure: 60% of equity
  - Max per-symbol concentration: 15% of equity
- **Position Limits**: Max 8 open positions simultaneously
- **Daily Trade Caps**: Limit 10 trades per day (configurable)
- **Circuit Breaker**: Auto-stop trading if daily loss exceeds -5%
- **Correlation Prevention**: Avoids opening too many correlated positions

**📊 Performance Tracker (`utils/performance_tracker.py`)**
- **Trade Performance Analytics**: Tracks every trade with market context
- **Win Rate Analysis**: By strategy type, market regime, and market mood
- **AI Accuracy Monitoring**: Compares predicted vs actual success rates
- **Auto-Calibration**: Recommends threshold adjustments based on results
- **Weekly Reports**: Automated performance summaries
- **Continuous Learning**: System improves based on historical results

### How It All Works Together

**Decision Flow (Every 60 seconds):**
1. **Market Analysis**: Market Intelligence analyzes 531 symbols
2. **Regime Classification**: Each symbol categorized (Trending/Sideways/etc)
3. **Strategy Selection**: System auto-selects best approach (Regular/GRID/Wait)
4. **Adaptive Prompt**: AI receives regime-optimized instructions
5. **Dynamic Thresholds**: RR requirements adapt to conditions (1.2-1.5+)
6. **Quality Filtering**: Multi-layer validation (AI → Dynamic → Portfolio)
7. **Portfolio Check**: Exposure limits and correlation analysis
8. **Telegram Approval**: User approves high-quality proposals
9. **Performance Tracking**: Results logged for continuous improvement

**Example Scenarios:**
- **Strong Bullish Trend**: AI receives "aggressive long" prompt with RR≥1.2, focuses on breakouts
- **Weak Sideways Market**: AI receives "GRID" prompt, looks for range-bound setups
- **Choppy Volatile**: AI receives "ultra-selective" prompt with RR≥1.5, most setups rejected
- **Portfolio Full**: New trades blocked even if high quality (risk management)

### System Capabilities

The Self-Adaptive Engine enables AlgoGPT to:
✅ **Adapt to Any Market**: Bullish, bearish, sideways, choppy - always has a strategy
✅ **Maximize Profit**: Different approach for each regime optimizes returns
✅ **Minimize Risk**: Portfolio intelligence prevents over-exposure
✅ **Learn Continuously**: Performance tracker enables auto-improvement
✅ **Scale Intelligently**: From 0 to 10 trades/day based on opportunities
✅ **Stay Disciplined**: Automated limits prevent emotional trading
✅ **Protect Capital**: Circuit breakers and drawdown protection

## External Dependencies

-   **Binance Futures API**: For real-time market data, order execution, and account management.
-   **OpenAI API**: Used for AI-powered trade proposal generation and market analysis.
-   **Telegram Bot API**: For sending real-time notifications, managing approval workflows, and handling interactive callbacks.
-   **Gunicorn**: Production-grade WSGI HTTP server.
-   **Prometheus**: For exposing application metrics.