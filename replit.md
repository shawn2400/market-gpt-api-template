# AlgoGPT - Algorithmic Trading Platform

## Overview

AlgoGPT is a comprehensive algorithmic trading platform built with FastAPI and Python. It provides real-time trading orchestration for Binance Futures with features including:

- **Trading Operations**: Automated trade execution with MARKET, HYBRID, and AUTO modes
- **Live Trade Management**: Advanced position management with TP/SL, trailing stops, break-even logic
- **Scanner & Analytics**: Multi-timeframe technical analysis with quality scoring
- **Risk Management**: Daily caps, position sizing, and pre-trade validation
- **Operations Approval**: Secure ticket-based approval system with HMAC authentication
- **API & Monitoring**: RESTful API with Prometheus metrics and health endpoints

**Current Status**: Running in demo mode with trading disabled by default

## Project Architecture

### Backend (FastAPI)
- **Main Application**: `main.py` - Core FastAPI app with all routes and business logic
- **Configuration**: `gunicorn_conf.py` - Gunicorn server configuration
- **Environment**: `.env` - Environment variables (not committed)

### Key Components
- **Routes**: Organized in `routes/` directory for modular endpoint management
- **Utilities**: Common functions in `utils/` for trading, analysis, and integration
- **Policies**: YAML-based configuration in `policies/` for dynamic strategy management
- **Static Files**: Dashboard UI in `static/dashboard/`

### Database & Storage
- **Trades Log**: JSON-based storage in `data/trades_log.json`
- **Redis**: Optional Redis integration for caching and anti-replay (configured via REDIS_URL)

## Setup Instructions

### Environment Configuration

The project uses environment variables defined in `.env`. Key variables:

**Server Settings**:
- `PORT=5000` - Server port (required for Replit)
- `BIND_HOST=0.0.0.0` - Bind to all interfaces

**Security**:
- `API_BEARER_TOKEN` - Bearer token for API authentication
- `OPS_SIGN_SECRET` - HMAC secret for signed operations

**Trading** (Disabled by default):
- `AUTO_RUN=false` - Auto-trading disabled
- `EXECUTE_TRADES=false` - Trade execution disabled
- `BINANCE_API_KEY` - Binance API key (not set in demo)
- `BINANCE_API_SECRET` - Binance API secret (not set in demo)

**Optional Integrations**:
- `OPENAI_API_KEY` - For AI-powered analysis (disabled by default)
- `TELEGRAM_BOT_TOKEN` - For Telegram notifications (not set in demo)
- `REDIS_URL` - For caching and state management (optional)

### Running the Application

The application runs automatically via the configured workflow:
```bash
PORT=5000 gunicorn -c gunicorn_conf.py main:app
```

To manually restart the server, use the workflow controls in Replit.

## API Endpoints

### Public Endpoints
- `GET /` - Service info and configuration
- `GET /healthz` - Health check
- `GET /readyz` - Readiness check
- `GET /version` - Version information
- `GET /docs` - Interactive API documentation (Swagger UI)
- `GET /redoc` - Alternative API documentation

### Protected Endpoints (require API_BEARER_TOKEN)
- `POST /ops/ticket` - Create operations ticket
- `POST /ops/approve` - Approve operation
- `GET /ops/ui` - Operations UI
- Various trading, analysis, and management endpoints

## Security

### Authentication Methods
1. **Bearer Token**: Include `Authorization: Bearer <token>` header
2. **HMAC Signature**: For critical operations, requires signed requests with X-Timestamp, X-Nonce, X-Signature headers

### Safety Features
- Trading is **DISABLED** by default in this Replit setup
- API bearer token protection on sensitive endpoints
- Anti-replay protection with Redis (when configured)
- Binance account mutations disabled by default

## Development

### File Structure
```
.
├── main.py                 # Main application file
├── gunicorn_conf.py       # Gunicorn configuration
├── requirements.txt       # Python dependencies
├── .env                   # Environment variables (not committed)
├── routes/                # API route modules
├── utils/                 # Utility functions
├── policies/              # Strategy policies (YAML)
├── static/                # Static files and dashboard
├── config/                # Configuration files
├── monitoring/            # Prometheus/Grafana configs
└── data/                  # Runtime data storage
```

### Adding Dependencies
Add packages to `requirements.txt` and run:
```bash
pip install -r requirements.txt
```

## Deployment

The project is configured for VM deployment on Replit with:
- **Deployment Target**: VM (stateful)
- **Run Command**: `gunicorn -c gunicorn_conf.py main:app`
- **Port**: Automatically set to 5000 for Replit compatibility

### Production Considerations

Before deploying to production:
1. Set strong random values for `API_BEARER_TOKEN` and `OPS_SIGN_SECRET`
2. Configure Binance API credentials if trading is desired
3. Set `EXECUTE_TRADES=true` and `AUTO_RUN=true` only when ready
4. Configure Redis URL for better state management
5. Set up Telegram notifications if desired
6. Review and adjust risk management settings in `.env`

## Monitoring

- **Metrics**: Available at `/metrics` (requires Bearer token)
- **Health Checks**: `/healthz`, `/readyz`, `/readyz/strict`
- **Logs**: Available in workflow console

## User Preferences

None configured yet. This is a fresh import.

## Recent Changes

- **2025-10-30**: Initial Replit setup
  - Installed Python 3.11 and all dependencies
  - Created `.env` with safe defaults (trading disabled)
  - Configured workflow to run on port 5000
  - Set up deployment configuration for VM target
  - Verified API is working correctly

## Troubleshooting

### Server won't start
- Check workflow logs for errors
- Verify all dependencies are installed: `pip install -r requirements.txt`
- Ensure PORT environment variable is set to 5000

### API returns 401 Unauthorized
- Check that `API_BEARER_TOKEN` is set in `.env`
- Include `Authorization: Bearer <token>` header in requests

### Trading not working
- This is expected! Trading is **disabled by default** for safety
- To enable: Set `EXECUTE_TRADES=true` and configure Binance credentials
- Never enable trading without understanding the risks

## Links

- **API Documentation**: `/docs` (Swagger UI)
- **Alternative Docs**: `/redoc`
- **Health Check**: `/healthz`
- **Original Repository**: Check git remote for source

## Notes

This is an algorithmic trading platform. Trading involves significant financial risk. The default configuration has all trading features **disabled** for safety. Only enable trading features if you understand the risks and have properly configured and tested the system.
