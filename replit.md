# AlgoGPT - Algorithmic Trading Platform

## Overview
AlgoGPT is a comprehensive algorithmic trading platform built with FastAPI and Python, designed for real-time trading orchestration on Binance Futures. It automates trade execution, manages live positions with advanced TP/SL/trailing stops, incorporates multi-timeframe technical analysis, and includes robust risk management with daily caps and pre-trade validation. The platform features a secure, ticket-based approval system via Telegram, ensuring human oversight for trade execution.

## User Preferences
I prefer iterative development with clear, concise communication. Please ask for my approval before making any major changes or executing trades. Provide detailed explanations for complex concepts but keep status updates brief and to the point. I like to have visibility into the system's decision-making process, especially regarding trade proposals and risk management. I prefer using interactive menus and quick scripts for common operations.

## System Architecture

### Backend
The core application is built with FastAPI (`main.py`) and uses Gunicorn for serving. Key functionalities are modularized into `routes/` (for API endpoints like context, alerts, and Telegram callbacks) and `utils/` (for common functions like HMAC, authentication, and trade execution). Policies are managed via YAML files in `policies/`.

### Key Features
- **Automated Trading Modes**: Supports MARKET, HYBRID, and AUTO execution modes.
- **Live Trade Management**: Dynamic management of open positions with Take Profit (TP), Stop Loss (SL), Break-Even (BE) logic, and ATR-based trailing stops.
- **Market Scanner**: An autonomous worker (`workers/gpt_auto_suggest.py`) performs multi-timeframe technical analysis every 60 seconds across Binance Futures markets, using an integrated Context API.
- **AI-Powered Proposals**: OpenAI GPT-4 analyzes market data and generates trade proposals.
- **Risk Management**: Implements strict quality filters (e.g., Risk/Reward > 1.6-1.9, AI success probability > 70%), liquidity checks, cooldown periods, deduplication, and daily trade caps.
- **Telegram Approval Workflow**: Trade proposals are sent to Telegram with rich details and interactive buttons for approval or rejection, requiring HMAC-signed confirmation for execution.
- **Dynamic Position Management**: Features like Break-Even Guard, ATR Trailing, and Multi-Target TP are automatically applied to managed positions.
- **Auto-Flip**: The system dynamically adapts to market conditions, proposing LONG or SHORT trades based on real-time analysis without manual intervention.

### UI/UX
A dashboard UI is located in `static/dashboard/`. Telegram notifications are enhanced with rich HTML formatting, emojis, and inline interactive buttons for a better user experience.

### Technical Implementations
- **Authentication**: Uses Bearer Token (`X-API-Key`) and HMAC Signature for secure access and critical operations.
- **Security**: Includes anti-replay protection, strict quality filters, multi-layer risk management, and mandatory Telegram approval for trade execution.

## External Dependencies

-   **Binance Futures API**: For real-time market data, order execution, and account management.
-   **OpenAI API**: Used for AI-powered trade proposal generation and market analysis.
-   **Telegram Bot API**: For sending real-time notifications, managing approval workflows, and handling interactive callbacks.
-   **Gunicorn**: Production-grade WSGI HTTP server.
-   **Prometheus**: For exposing application metrics.