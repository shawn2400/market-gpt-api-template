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
1. **Enhanced AI Prompt**: Changed from weak "Favor RR≥1.6" to mandatory "RR≥1.3 MINIMUM, TARGET ≥1.5-2.0" with concrete examples.
2. **AI Response Validation**: Added early rejection of proposals with RR<1.2 or unrealistic success_pct.
3. **GRID Trading Integration**: Connected grid_builder.py, grid_manager.py, and routes/grid.py to main.py; enabled SUGGEST_GRID=1 in Auto Scanner.
4. **Telegram Visual Tagging**: Added 🔷 GRID Trade vs ⚡ Futures/Spot Trade labels in approval messages.
5. **Validated Existing Infrastructure**: Confirmed ATR Trailing, Multi-TP, Position Sizing, and MARKET Orders are all implemented and working.

## External Dependencies

-   **Binance Futures API**: For real-time market data, order execution, and account management.
-   **OpenAI API**: Used for AI-powered trade proposal generation and market analysis.
-   **Telegram Bot API**: For sending real-time notifications, managing approval workflows, and handling interactive callbacks.
-   **Gunicorn**: Production-grade WSGI HTTP server.
-   **Prometheus**: For exposing application metrics.