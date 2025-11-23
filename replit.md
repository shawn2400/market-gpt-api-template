# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is an autonomous AI-driven algorithmic trading platform designed for 24/7 operation on Binance Futures. It analyzes 534 symbols, executing intelligent trades based on 7 integrated strategies and dynamic capital management. The platform features an AI-driven MetaBrain that determines all trade parameters, aiming for 4-10 high-quality daily trades. It prioritizes scalability, autonomous operation through a self-adaptive engine, and complete data persistence, optimized for diverse market conditions. The business vision is to provide a robust, self-optimizing algorithmic trading solution with high market potential due to its autonomous and AI-driven adaptability.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations. All communication in Hebrew. Automatic trading with 100% dynamic automation - no time-based patterns. SL/TP fully dynamic. Budget scales with wallet size automatically. All features must activate dynamically/automatically when system is ready.

## System Architecture

### UI/UX
The system provides a dashboard UI and enhanced Telegram notifications, utilizing HTML formatting, emojis, and inline interactive buttons for user interaction. Weekly Reports and ULTRA-PLUS dashboards provide comprehensive real-time monitoring.

### Technical Implementations
The core application is built with FastAPI and Gunicorn, emphasizing modularity and policy management via YAML files. All critical data is saved to a PostgreSQL database. All ULTRA-PLUS systems operate with dynamic auto-activation.

**Core Features:**
- **Automated Trading Modes**: Supports MARKET, HYBRID, and FULL AUTO execution with dynamic management of open positions (TP, SL, BE logic, ATR-based trailing stops, auto-flip).
- **Market Scanner**: Autonomous multi-timeframe technical analysis across Binance Futures with weighted trend detection.
- **AI-Powered Proposals**: Uses DeepSeek Chat for trade decisions with adaptive Risk/Reward, intelligent brain management, and dynamic quality threshold enforcement.
- **Resilient Trade Generation**: Two-tier proposal system: Primary (AI-driven) and Fallback (Technical-only, with Technical Strategy Selector and Trade Generator). Automatically switches between modes with zero downtime.
- **GRID Trading**: Integrated FUTURES GRID trading with dynamic symbol selection, tiered strategies, dynamic sizing, and automatic SL/TP protection.
- **Risk Management**: Includes quality filters, dynamic filters, liquidity checks, cooldowns, daily trade caps, and a circuit breaker, alongside a Dynamic Budget System and Dynamic SL/TP Calculation (ATR-based).
- **Multi-User Support + RBAC**: Full user management with admin/user/viewer roles, Telegram auth, and API key management.
- **Advanced Monitoring**: Real-time tracking of auto-switches, SL-saves, missed trades, locked profit, and automated weekly reports.
- **ULTRA-PLUS Systems**: Seven advanced systems: ML Predictor (price forecasting), Freeze Manager (auto-freeze risky symbols), Performance Heatmap (win/loss tracking), Profit-Share System (automatic billing), Auto-Withdraw (profit extraction), Insurance Mode (auto-hedge detection), and Anomaly Detector (critical anomaly detection).
- **MetaBrain - AI-Driven Precision Trading**: Features a 3-stage auto-deployment engine, 1-Brain Lean Architecture, intelligent brain management, regime-based dynamic MIN_QUALITY, and a regime detection engine.
- **Adaptive Win Rate Optimizer**: Tracks performance, calculates Sharpe ratio, adjusts position sizing, and scales SL/TP based on confidence.
- **ExecutionBot**: Centralized architecture for all trade execution logic with source-aware approval gating and Stage Engine integration.
- **Auto-Optimization System**: Self-adaptive trading through intelligent parameter tuning, multi-level protection, and dynamic blacklist management.
- **Insurance Monitor System**: Multi-layered account protection including Drawdown Protection, Margin Ratio Defense, Cross/Isolated Balancer, and a Circuit Breaker.
- **Validation & Safety Infrastructure**: Comprehensive validation pipeline, fail-closed decision gates, Monte Carlo simulations, Live Health Monitor, and a 3-Layer Emergency Protection System.
- **Order Management**: Smart LIMIT+MARKET Order Router, Order Consolidation System, Hybrid Dynamic Leverage System, and Binance Symbol Validator.
- **Trading Policy Filters**: System-wide protection via Symbol Filter Engine, Adaptive Volume Filter Integration, Market-Aware Threshold Selection, and Position Limits Manager.
- **Dynamic Smart Filter**: Regime-Aware + AUTO Percentile Strategy for adaptive volume analysis, dynamic BTC correlation penalty, and market intelligence integration.
- **Critical AutoFix Engine**: Auto-detects and fixes critical issues (precision, order execution, position management, risk) with real-time monitoring.
- **Intelligent Trading Features**: Pattern Recognition Engine, Adaptive Confidence Weights, Win Rate Optimizer, and Symbol-Specific Trading Rules.
- **Quantum Trading Council System**: A 7-member expert AI council with weighted voting for trade qualification and strategy routing.
- **External Brain Integration System**: A 6-bot cooperative trading team (Cryptohopper, 3Commas, WunderTrading, HyperTrader, Bybit Signals, TradingView) with dynamic capabilities, failover, and self-learning.

### Deployment Architecture
The production environment runs on Render.com with Background Workers and a Neon PostgreSQL database, connected to GitHub for auto-deployment. Replit is used for development with ALGO-REPLIT self-hosted development infrastructure running on port 8000.

### Current System Status (Development)
- **AlgoGPT Server**: Running on port 5000 (Gunicorn + FastAPI)
- **ALGO-REPLIT Core Control Server**: Running on port 8000 (FastAPI + Uvicorn)
  - Provides infrastructure management, code editing, and AI integration
  - Three core modules: core_control_server.py (main controller), ollama_ai_agent.py (local AI), scale_manager.py (resource scaling)
  - Auto-activation enabled - all features activate dynamically when resources available ("הכול יופעל דינמי אוטומטי")

### Active Workflows in Replit
Currently optimized to 2 workflows (due to port constraints):
1. **AlgoGPT Server** (port 5000) - Main trading system
2. **ALGO-REPLIT Core Control Server** (port 8000) - Development infrastructure

Consolidated workflows (can be re-enabled):
- Auto Scanner, Fills Watcher, GPT-5 Central Brain, Position Monitor, Sentinel Security, Auto Health Monitor
- Daily Meeting 00:00, Telegram Digest Reporter (scheduled tasks)

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
-   **Cryptohopper**: External scanner for market analysis.
-   **3Commas**: External manager for smart position management.
-   **WunderTrading**: External signals relay system.
-   **HyperTrader**: External execution for fast order routing.
-   **Bybit Signals**: External futures signals.
-   **TradingView**: External webhooks & indicators.