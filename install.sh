#!/bin/bash
set -e

echo "════════════════════════════════════════════════════════════"
echo "✅ AlgoGPT v10.4.0 - One-Click Installation"
echo "════════════════════════════════════════════════════════════"

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose not installed. Please install it first."
    exit 1
fi

# Check/Create config file
if [ ! -f ".env" ]; then
    echo "📋 Creating .env from config.env..."
    cp config.env .env
    echo "⚠️  Please edit .env with your settings"
fi

echo "🛑 Stopping any existing containers..."
docker-compose down || true

echo "🏗️  Building Docker images..."
docker-compose build --no-cache

echo "🚀 Starting services..."
docker-compose up -d

echo "⏳ Waiting for services to be ready (30s)..."
sleep 30

echo "✅ Verifying health checks..."
curl -fsS http://localhost:8008/readyz || {
    echo "❌ API health check failed!"
    exit 1
}

echo ""
echo "════════════════════════════════════════════════════════════"
echo "🎉 AlgoGPT v10.4.0 - FULLY OPERATIONAL!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "📍 Services Available:"
echo "   API Backend:    http://localhost:8008"
echo "   API Docs:       http://localhost:8008/docs"
echo "   Health Check:   http://localhost:8008/readyz"
echo ""
echo "📊 Next Steps:"
echo "   1. Check /logs for system messages"
echo "   2. Configure Telegram bot (optional)"
echo "   3. Set API keys in .env"
echo "   4. Monitor via logs: docker-compose logs -f"
echo ""
echo "🚀 System ready for 24/7 operation!"
echo ""
