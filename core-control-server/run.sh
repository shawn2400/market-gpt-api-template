#!/bin/bash

# ALGO-REPLIT Core Control Server
# Runs directly in Replit (no Docker needed)

set -e

echo "🚀 Starting ALGO-REPLIT Core Control Server..."
echo "📍 Server will run on http://0.0.0.0:8000"
echo "📚 API docs: http://localhost:8000/docs"
echo ""

# Install dependencies
echo "📦 Installing dependencies..."
pip install -q -r requirements.txt

# Create workspace
mkdir -p workspaces
export ADMIN_TOKEN="${ADMIN_TOKEN:-change_me_in_production}"

echo "✅ Setup complete!"
echo ""
echo "Starting server..."
uvicorn app.main:app --host 0.0.0.0 --port 8000
