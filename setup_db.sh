#!/bin/bash
# ================================================================================
# PostgreSQL Setup Script for Render
# ================================================================================
# This script installs and configures PostgreSQL on your Render server
# ================================================================================

set -e  # Exit on error

echo "🗄️ Setting up PostgreSQL..."

# Check if PostgreSQL is already installed
if command -v psql &> /dev/null; then
    echo "✅ PostgreSQL is already installed"
    exit 0
fi

echo "📦 Installing PostgreSQL..."

# Detect OS and install accordingly
if [ -f /etc/debian_version ]; then
    # Debian/Ubuntu
    echo "  → Detected Debian/Ubuntu"
    sudo apt-get update -qq
    sudo apt-get install -y -qq postgresql postgresql-contrib libpq-dev
elif [ -f /etc/redhat-release ]; then
    # Red Hat/CentOS
    echo "  → Detected Red Hat/CentOS"
    sudo yum install -y postgresql-server postgresql-contrib postgresql-devel
    sudo postgresql-setup initdb
else
    echo "❌ Unsupported OS for automatic PostgreSQL installation"
    echo "Please install PostgreSQL manually and set DATABASE_URL environment variable"
    exit 1
fi

# Start PostgreSQL service
echo "🔧 Starting PostgreSQL service..."
sudo service postgresql start || sudo systemctl start postgresql

# Create database and user
echo "👤 Creating database and user..."
sudo -u postgres psql -c "CREATE USER algogpt_user WITH PASSWORD 'algogpt_password_change_me';" || true
sudo -u postgres psql -c "CREATE DATABASE algogpt_production OWNER algogpt_user;" || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE algogpt_production TO algogpt_user;" || true

echo "✅ PostgreSQL setup complete!"
echo ""
echo "⚠️  IMPORTANT: Update your DATABASE_URL in Render dashboard:"
echo "   postgresql://algogpt_user:algogpt_password_change_me@localhost/algogpt_production"
echo ""
