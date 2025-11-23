#!/bin/bash

set -e

# ALGO-REPLIT Installation Script
# One-command bootstrap for complete setup

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "╔════════════════════════════════════════════════════╗"
echo "║   ALGO-REPLIT System Installation (v1.0)          ║"
echo "╚════════════════════════════════════════════════════╝"

# Check prerequisites
echo "✓ Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose."
    exit 1
fi

echo "✓ Docker & Docker Compose found"

# Create directories
echo "✓ Creating workspace directories..."
mkdir -p "$PROJECT_ROOT/workspaces"
mkdir -p "$PROJECT_ROOT/backups"
mkdir -p "$PROJECT_ROOT/logs"

# Create environment file
echo "✓ Creating environment configuration..."
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    cat > "$SCRIPT_DIR/.env" << EOF
# ALGO-REPLIT Environment Configuration

# Admin token (CHANGE THIS)
ADMIN_TOKEN=admin_default_token_change_me

# Scale mode (false = single-user, true = multi-user/scaled)
ENABLE_SCALE_MODE=false

# Database
POSTGRES_DB=algoreplit
POSTGRES_USER=admin
POSTGRES_PASSWORD=secure_password_change_me

# Redis
REDIS_URL=redis://redis:6379

# Ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama2

# Logging
LOG_LEVEL=INFO

# Backup retention (days)
BACKUP_RETENTION_DAYS=7
EOF
    echo "  .env file created. Please update with your values."
else
    echo "  .env file already exists (skipped)"
fi

# Build Docker images
echo "✓ Building Docker images..."
cd "$SCRIPT_DIR"
docker-compose build --no-cache

# Start services
echo "✓ Starting services..."
docker-compose up -d

# Wait for services to be healthy
echo "✓ Waiting for services to start..."
sleep 10

# Check Redis
echo "✓ Checking Redis..."
if docker-compose exec redis redis-cli ping &> /dev/null; then
    echo "  ✓ Redis is running"
else
    echo "  ⚠️  Redis not responding yet, may still be starting"
fi

# Check PostgreSQL
echo "✓ Checking PostgreSQL..."
if docker-compose exec postgres pg_isready -U admin &> /dev/null; then
    echo "  ✓ PostgreSQL is running"
else
    echo "  ⚠️  PostgreSQL not responding yet"
fi

# Check Ollama
echo "✓ Checking Ollama..."
if curl -s http://localhost:11434/api/tags &> /dev/null; then
    echo "  ✓ Ollama is running"
    echo "  📝 Pulling models: llama2, mistral..."
    docker-compose exec ollama ollama pull llama2 &
    docker-compose exec ollama ollama pull mistral &
else
    echo "  ⚠️  Ollama not responding yet"
fi

# Check Core Control Server
echo "✓ Checking Core Control Server..."
if curl -s http://localhost:8001/health &> /dev/null; then
    echo "  ✓ Core Control Server is running"
else
    echo "  ⚠️  Core Control Server not responding yet"
fi

echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║   Installation Complete! 🎉                       ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""
echo "📍 Access Points:"
echo "  • Dashboard: http://localhost:5173"
echo "  • API Docs: http://localhost:8001/docs"
echo "  • Ollama: http://localhost:11434"
echo "  • Redis: localhost:6379"
echo "  • PostgreSQL: localhost:5432"
echo ""
echo "🔐 Default Admin Token: $(grep ADMIN_TOKEN "$SCRIPT_DIR/.env" | cut -d= -f2)"
echo ""
echo "📚 Next Steps:"
echo "  1. Update .env file with secure credentials"
echo "  2. Access dashboard at http://localhost:5173"
echo "  3. Create your first project"
echo "  4. Read documentation: docs/SETUP.md"
echo ""
echo "⚠️  Important:"
echo "  • Change ADMIN_TOKEN in .env immediately"
echo "  • Set ENABLE_SCALE_MODE=true when ready for multi-user"
echo "  • Review security settings before production use"
echo ""

# Display logs
echo "📊 Service Status:"
docker-compose ps

echo ""
echo "✅ All systems ready for AlgoGPT integration!"
