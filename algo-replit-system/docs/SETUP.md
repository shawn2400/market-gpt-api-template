# ALGO-REPLIT System Setup Guide

## Overview

ALGO-REPLIT is a self-hosted, full-featured development environment integrated with AlgoGPT. It provides:

- 🎯 **Single-user mode** (now) with dormant multi-user features
- 🔄 **Auto-scaling ready** - activates when resources grow
- 💻 **Web IDE Dashboard** - file explorer, editor, terminal
- 🤖 **Local AI (Ollama)** - code generation, modification, debugging
- 📦 **Project Management** - create, run, test, deploy projects
- 🔒 **Security** - admin-only access, audit logging, emergency freeze
- 💾 **Backup/Restore** - automatic nightly backups, 7-day retention
- 🔗 **AlgoGPT Integration** - edit code, run tests, apply patches

## Quick Start

### Prerequisites

- Docker & Docker Compose
- 8GB+ RAM recommended
- 20GB disk space

### Installation

```bash
cd algo-replit-system/docker
bash install.sh
```

This will:
1. Check prerequisites
2. Build Docker images
3. Start all services (Redis, PostgreSQL, Ollama, Core Server)
4. Download AI models
5. Provide access URLs

### First Login

1. Open http://localhost:5173 in your browser
2. Enter admin token from `.env` file
3. Create your first project
4. Start developing!

## Configuration

### Environment Variables (.env)

```bash
# Security
ADMIN_TOKEN=your_secure_token_here

# Scaling
ENABLE_SCALE_MODE=false  # Set to true for multi-user

# Database
POSTGRES_PASSWORD=change_me_in_production

# AI
OLLAMA_MODEL=llama2
```

## Features

### Dashboard

- **System Status** - CPU, memory, disk, resource monitoring
- **Projects** - create, list, delete, clone projects
- **Services** - start/stop/restart running services
- **Logs** - real-time streaming of service logs

### Code Editor

- **File browser** - navigate project structure
- **Monaco editor** - syntax highlighting, autocomplete
- **Save/load** - instantly save changes
- **Integration** - edit AlgoGPT files directly

### Terminal

- **Live terminal** - execute commands in projects
- **Output streaming** - WebSocket-based log streaming
- **Service control** - start/stop processes

### AI Assistant

- **Chat interface** - natural language conversation
- **Code generation** - generate code from prompts
- **Code modification** - request changes to existing code
- **Error explanation** - understand error messages
- **Local models** - Ollama (no API keys needed!)

### Project Management

- **Create projects** - Python, Node.js templates
- **Run scripts** - execute run.sh or custom commands
- **Test execution** - run pytest or npm test
- **Clone from Git** - import existing repositories
- **Isolation** - each project in its own environment

### Backup & Restore

- **Automatic backups** - every 24 hours
- **7-day retention** - rolling backup window
- **One-click restore** - restore previous state
- **Safe mode** - backs up current state before restore
- **Export** - download backups as zip/tar.gz

### Security

- **Admin-only access** - single user, token-based
- **Audit logging** - every action tracked
- **Emergency freeze** - stop all operations instantly
- **Confirmation gates** - critical ops require approval
- **Sandboxed file access** - can't access outside paths

## Dormant Features (Auto-Activate When Needed)

### Multi-User Mode
- Enabled when: `ENABLE_SCALE_MODE=true`
- Provides: API isolation, wallet separation, permission tiers
- Status: Inactive (single-user now)

### Load Balancing
- Enabled when: Multiple requests overload single server
- Provides: Request distribution, fault tolerance
- Status: Dormant (single server now)

### Multi-Node Replication
- Enabled when: Scale mode + multiple servers
- Provides: High availability, auto-failover
- Status: Dormant (single node now)

## AlgoGPT Integration

### Edit AlgoGPT Code

```
1. Open file explorer
2. Navigate to /algogpt
3. Select file to edit
4. Make changes
5. Click "Save"
```

### Run AlgoGPT Tests

```bash
# Via API
POST /algogpt/run_tests

# Via Dashboard
Dashboard → Projects → AlgoGPT → Run Tests
```

### Apply Patches

1. AI suggests improvements
2. Click "Apply Patch"
3. Patch logged for review
4. Admin confirms in audit log
5. Patch applied to codebase

## Monitoring

### Health Checks

- Redis: `curl http://localhost:6379`
- Database: Check in Dashboard
- API: `curl http://localhost:8001/health`
- AI: `curl http://localhost:11434/api/tags`

### Logs

- **Core Server**: `/logs/core_control_server.log`
- **Services**: WebSocket streaming in dashboard
- **Audit**: `/logs/audit.log`
- **Database**: Container logs via `docker-compose logs`

## Scaling

### Enable Scale Mode

```bash
# Edit .env
ENABLE_SCALE_MODE=true

# Restart
docker-compose down
docker-compose up -d
```

This activates:
- Multi-user isolation
- Wallet separation
- Load balancing infrastructure
- Profit-share automation
- API isolation per user

### Auto-Scaling Triggers

System automatically expands when:
- CPU > 80%
- Memory > 85%
- Queue size > 50 items
- Multiple symbols trading simultaneously

## Troubleshooting

### Services won't start

```bash
# Check logs
docker-compose logs -f core-control-server

# Restart
docker-compose restart
```

### Ollama models not downloaded

```bash
# Pull models manually
docker-compose exec ollama ollama pull llama2
docker-compose exec ollama ollama pull mistral
```

### Database connection error

```bash
# Reset database
docker-compose down -v
docker-compose up -d postgres
# Wait 30s for initialization
```

### Out of memory

```bash
# Increase Docker limits
# Edit ~/.docker/config.json or Docker Desktop settings
# Restart: docker-compose restart
```

## Production Deployment

### Using Docker Swarm

```bash
docker swarm init
docker stack deploy -c docker-compose.yml algoreplit
```

### Using Kubernetes

```bash
# Convert docker-compose to K8s manifests
kompose convert -f docker-compose.yml -o k8s/

# Deploy
kubectl apply -f k8s/
```

### Environment Setup

```bash
# Generate secure admin token
openssl rand -hex 32

# Set production secrets
ADMIN_TOKEN=$(openssl rand -hex 32)
POSTGRES_PASSWORD=$(openssl rand -hex 32)

# Update .env with production values
```

## API Reference

### Authentication

All requests require `?token=ADMIN_TOKEN`

### Projects

- `GET /projects` - List all projects
- `POST /projects/create` - Create new project
- `GET /projects/{name}` - Get project details
- `POST /projects/{name}/delete` - Delete project

### Files

- `POST /files/read` - Read file
- `POST /files/write` - Write file
- `POST /files/delete` - Delete file

### Services

- `GET /services` - List running services
- `POST /services/start` - Start service
- `POST /services/stop` - Stop service
- `POST /services/restart` - Restart service

### AlgoGPT

- `GET /algogpt/files` - List AlgoGPT files
- `POST /algogpt/run_tests` - Run unit tests
- `POST /algogpt/apply_patch` - Apply code patch

### Backup

- `POST /backup/create` - Create backup
- `GET /backup/list` - List backups
- `POST /backup/restore` - Restore from backup
- `POST /backup/export` - Export backup

### Safety

- `POST /emergency/freeze` - Stop all operations
- `POST /emergency/unfreeze` - Resume operations
- `GET /audit/logs` - Get audit trail

## Support

For issues:
1. Check logs: `docker-compose logs`
2. Review audit: Dashboard → Audit Logs
3. Test health: `/health` endpoint
4. Emergency: Dashboard → Emergency Freeze

For AlgoGPT specific issues:
- See `/algogpt/DEPLOYMENT.md`
- Check configuration: `/algogpt/config`
- Review logs: Telegram notifications
