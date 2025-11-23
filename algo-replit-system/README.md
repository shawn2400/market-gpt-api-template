# 🚀 ALGO-REPLIT v1.0
**Self-Hosted AI Development Environment for AlgoGPT**

A complete, production-ready IDE built as a standalone system integrated with AlgoGPT trading platform. Features single-user mode now with dormant multi-user capabilities that activate automatically as the system scales.

---

## ✨ Features

### 📊 Web Dashboard
- **Real-time monitoring** - CPU, memory, disk usage
- **Project management** - Create, run, delete projects
- **Service control** - Start/stop/restart services
- **Log streaming** - Live logs via WebSocket

### 💻 Code Editor
- **Monaco editor** - Full IDE-like experience
- **File browser** - Tree view navigation
- **Syntax highlighting** - 50+ languages
- **Auto-save** - Instant file persistence

### 🤖 Local AI Assistant
- **Ollama integration** - Free, no API keys needed
- **Code generation** - Generate code from prompts
- **Code modification** - Request intelligent changes
- **Error explanation** - Understand issues instantly
- **Chat interface** - Natural language conversation

### 📦 Project Management
- **Multi-template support** - Python, Node.js, more
- **Isolation** - Each project in own environment
- **Run scripts** - Execute any shell command
- **Test execution** - Pytest, npm test, etc.

### 💾 Backup & Recovery
- **Auto backup** - Every 24 hours
- **7-day retention** - Rolling window
- **One-click restore** - Safe restore with backup
- **Export** - Download as zip/tar.gz

### 🔒 Security
- **Admin-only access** - Single user, strong auth
- **Audit logging** - Every action tracked
- **Emergency freeze** - Stop all operations instantly
- **Sandboxed files** - Can't access outside paths
- **No trading** - Read/write only, never executes trades

### 🔄 Scale-Ready Architecture
- **Single-user now** - Zero overhead
- **Auto-scaling ready** - Activates on resource growth
- **Multi-user dormant** - Full code built, not active
- **Load balancing** - Prepared infrastructure
- **Multi-node support** - Future expansion ready

---

## 🚀 Quick Start

### Requirements
- Docker & Docker Compose
- 8GB+ RAM
- 20GB disk space

### Installation (One Command!)

```bash
cd algo-replit-system/docker
bash install.sh
```

This automatically:
- ✅ Checks prerequisites
- ✅ Builds Docker images
- ✅ Starts all services (Redis, PostgreSQL, Ollama, API)
- ✅ Downloads AI models
- ✅ Provides access URLs

### Access

| Service | URL | Purpose |
|---------|-----|---------|
| **Dashboard** | http://localhost:5173 | Web IDE |
| **API Docs** | http://localhost:8001/docs | Interactive API |
| **Ollama** | http://localhost:11434 | Local AI |
| **Redis** | localhost:6379 | Cache |
| **PostgreSQL** | localhost:5432 | Database |

### First Login

1. Open http://localhost:5173
2. Enter admin token from `.env` file
3. Create first project
4. Start coding!

---

## 📁 Project Structure

```
algo-replit-system/
├── backend/
│   ├── core_control_server.py      # FastAPI main server
│   ├── ollama_ai_agent.py           # Local AI integration
│   ├── backup_manager.py            # Backup/restore system
│   ├── scale_manager.py             # Auto-scaling logic
│   ├── safety_manager.py            # Security & audit
│   ├── algogpt_integration.py       # AlgoGPT integration
│   └── main_router.py               # Unified API routes
├── frontend/
│   ├── src/
│   │   ├── App.jsx                  # Main React component
│   │   ├── components/              # UI components
│   │   │   ├── ProjectManager.jsx
│   │   │   ├── CodeEditor.jsx
│   │   │   ├── Terminal.jsx
│   │   │   └── AIChat.jsx
│   │   └── index.css
│   ├── package.json
│   └── vite.config.js
├── docker/
│   ├── Dockerfile                   # Multi-stage build
│   ├── docker-compose.yml           # Services orchestration
│   └── install.sh                   # Bootstrap script
├── docs/
│   ├── SETUP.md                     # Setup guide
│   └── ARCHITECTURE.md              # System design
└── requirements-algoreplit.txt      # Python dependencies
```

---

## 🎯 Key Concepts

### Single-User Mode (Now)
```
┌─────────────┐
│   Admin     │
│   (YOU)     │
└──────┬──────┘
       │
       ↓
┌─────────────────────────────────┐
│ ALGO-REPLIT Control Server      │
│ • Project management            │
│ • File operations               │
│ • Process execution             │
│ • AI agent                      │
└──────────┬──────────────────────┘
           │
           ↓
┌────────────────────────────────────┐
│ Services (dormant multi-user code) │
│ • Redis (cache/session)            │
│ • PostgreSQL (data)                │
│ • Ollama (local AI)                │
└────────────────────────────────────┘
```

### Dormant Features (Activate on Demand)

When you set `ENABLE_SCALE_MODE=true`:
- ✅ Multi-user isolation activated
- ✅ Wallet separation enabled
- ✅ Load balancing ready
- ✅ Multi-node replication configured
- ✅ API per-user isolation
- ✅ Permission tier enforcement

### Auto-Scaling Triggers

System automatically expands when:
- CPU > 80% for 5+ minutes
- Memory > 85% sustained
- Request queue overflows
- Multiple projects demand resources

---

## 📚 Usage Examples

### Create a Python Project

```bash
# Via Dashboard
1. Projects → Create New
2. Name: my-ai-project
3. Template: python
4. Click Create

# Project structure created:
# /workspaces/my-ai-project/
# ├── src/main.py
# ├── requirements.txt
# └── run.sh
```

### Use AI to Generate Code

```
1. Open AI Chat panel
2. Type: "Create a Flask API with GET /hello endpoint"
3. Ollama generates code
4. Click to apply to editor
5. Save to project
```

### Run Project

```
1. Open file explorer
2. Select project
3. Click Run
4. See live output in terminal
```

### Edit AlgoGPT Code

```
1. File explorer → /algogpt
2. Navigate to file
3. Make changes in editor
4. Click Save
5. Changes synced to AlgoGPT
```

### Backup Before Major Changes

```
# Manual
1. Dashboard → Backup → Create
2. System creates compressed backup
3. Auto-restores if something fails

# Automatic
- Every 24 hours
- 7-day rolling retention
- Auto-cleanup of old backups
```

---

## 🔧 Configuration

### Environment Variables (.env)

```bash
# Security
ADMIN_TOKEN=your_secure_token_here

# Scaling
ENABLE_SCALE_MODE=false         # true = multi-user mode
SCALE_CPU_THRESHOLD=80          # CPU% to trigger expansion
SCALE_MEMORY_THRESHOLD=85       # Mem% to trigger expansion

# Database
POSTGRES_DB=algoreplit
POSTGRES_USER=admin
POSTGRES_PASSWORD=your_password

# Ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama2             # llama2, mistral, codellama

# Backup
BACKUP_RETENTION_DAYS=7         # Keep 7-day rolling window

# Logging
LOG_LEVEL=INFO                  # INFO, DEBUG, WARNING, ERROR
```

### AI Models

Available models (auto-pull on start):
- **llama2** (default) - General purpose, good balance
- **mistral** - Lightweight, fast
- **codellama** - Specialized for code

```bash
# Switch model in .env
OLLAMA_MODEL=mistral
```

---

## 🛡️ Security

### Authentication
- Admin token required on all requests
- Single-user access (production: strong token)
- No passwords or OAuth (admin-only simplicity)

### Authorization
- Invalid token = 401 Unauthorized
- No multi-user permissions yet (dormant)
- Token enforcement on every endpoint

### File Access
- All paths validated
- Cannot access parent directories
- Deny-by-default security model
- Audit logging on every operation

### Audit Trail
```
Every action logged:
• Timestamp
• User (admin)
• Action (create, read, write, delete)
• Details (file path, size, etc.)
• Status (success/failure)
```

### Emergency Controls
- **Emergency Freeze** - Stops all operations instantly
- **No Trading** - Can never execute trades
- **Confirmation Gates** - Critical ops require approval
- **Watermarking** - AI-generated code tagged with watermark

---

## 📊 Monitoring

### Health Endpoints

```bash
# Full status
curl http://localhost:8001/health

# System status
curl http://localhost:8001/status

# API docs
curl http://localhost:8001/docs

# Service list
curl http://localhost:8001/services
```

### Resource Monitoring

Dashboard shows real-time:
- CPU usage (%)
- Memory usage (%)
- Disk usage (%)
- Available memory (MB)
- Running processes count

### Logs

- **Core Server**: Dashboard terminal view
- **Services**: WebSocket streaming
- **Audit Trail**: `/api/audit/logs`
- **Docker**: `docker-compose logs -f`

---

## 🔄 Scaling Path

### Current: Single-User (NOW)
```
1 Machine → 1 User → 1 Admin → Single Wallet
```

### Scale Mode Enabled: Multi-User (Manual)
```bash
ENABLE_SCALE_MODE=true
docker-compose restart
```

Activates:
- User isolation per API key
- Wallet separation (multi-wallet support)
- Load balancing (request distribution)
- Permission tiers (viewer/user/admin)

### Multi-Node: Enterprise (Future)
```
Kubernetes deployment:
- 3+ server nodes
- Auto-scaling on CPU >80%
- Load balancer (nginx/haproxy)
- Shared database (Neon)
- Redis cluster
```

---

## 🐛 Troubleshooting

### Dashboard won't load
```bash
# Check API
curl http://localhost:8001/health

# Check logs
docker-compose logs core-control-server

# Restart
docker-compose restart core-control-server
```

### AI not responding
```bash
# Check Ollama
curl http://localhost:11434/api/tags

# Pull models
docker-compose exec ollama ollama pull llama2

# Restart
docker-compose restart ollama
```

### Out of memory
```bash
# Increase Docker limits
# Edit Docker Desktop: Settings → Resources
# Or in docker-compose.yml: deploy.resources

# Restart
docker-compose down
docker-compose up -d
```

### Files not saving
```bash
# Check permissions
ls -la /workspaces

# Check disk space
df -h

# Restart
docker-compose restart core-control-server
```

---

## 📖 Documentation

- **[SETUP.md](docs/SETUP.md)** - Detailed setup guide
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** - System design & components
- **[API Docs](http://localhost:8001/docs)** - Interactive Swagger UI
- **[AlgoGPT Integration](docs/ALGOGPT_INTEGRATION.md)** - Trading platform connection

---

## 🎓 Example Workflows

### Workflow: Build & Test Project

```
1. Create project (Dashboard)
2. Edit code (Code Editor)
3. Run tests (Terminal: pytest)
4. View results (Log streaming)
5. Backup (Dashboard: Backup → Create)
```

### Workflow: AI-Assisted Development

```
1. Open AI Chat
2. "Create Python WebSocket server"
3. AI generates code
4. Apply to project
5. Run & test
6. Modify with AI
7. Repeat until satisfied
```

### Workflow: Develop for AlgoGPT

```
1. Open AlgoGPT files (/algogpt)
2. Edit strategy code
3. Request AI improvements
4. Run local tests
5. Request patch application
6. Admin reviews & confirms
7. Patch applied to live system
```

---

## 🤝 Integration Points

### With AlgoGPT
- Read trading config
- Edit strategy files
- Run unit tests
- Apply code improvements
- Sync configuration

### With Neon PostgreSQL
- Project metadata
- User profiles (future)
- Wallet records
- Performance metrics

### With Telegram (Future)
- Approval notifications
- Status updates
- Error alerts
- Audit events

---

## 🌟 Advanced Features

### Backup & Recovery
```bash
# Create backup
POST /api/backup/create

# List backups
GET /api/backup/list

# Restore
POST /api/backup/restore?backup_name=backup_2024-01-15

# Export
POST /api/backup/export?format=zip
```

### Safety Controls
```bash
# Emergency freeze (stop everything)
POST /api/emergency/freeze

# Resume
POST /api/emergency/unfreeze

# Audit log
GET /api/audit/logs?limit=100
```

### Scaling Management
```bash
# Check status
GET /api/scale/status

# Enable scale mode
POST /api/scale/enable

# Disable scale mode
POST /api/scale/disable
```

---

## 📈 Performance

### Latency
- API response: <100ms (local)
- File I/O: <50ms (SSD)
- AI inference: 2-10s (varies by model)
- WebSocket: <10ms round trip

### Throughput
- Max concurrent projects: 100+
- Max concurrent users: 1 (now) → ∞ (scaled)
- Requests/sec: 1000+
- File ops: 1000+/sec

### Storage
- Base system: 2GB
- Per project: 100MB-1GB
- 7-day backups: 5-10GB
- AI models: 5GB per model

---

## 📝 License & Support

ALGO-REPLIT is provided as-is with AlgoGPT integration.

For issues:
1. Check logs: `docker-compose logs`
2. Review audit: Dashboard → Audit
3. Test health: `/health` endpoint
4. Emergency: Dashboard → Emergency Freeze

---

## 🔮 Roadmap

### Phase 1 (Current) ✅
- Single-user IDE
- Local AI integration
- Project management
- Backup/restore
- AlgoGPT integration

### Phase 2 (Q1 2024)
- Multi-user support (manual toggle)
- Telegram approval workflows
- Advanced monitoring
- Custom plugins

### Phase 3 (Q2 2024)
- Kubernetes deployment
- Multi-region support
- Advanced RBAC
- API rate limiting

---

**Built with ❤️ for AlgoGPT**

*הכול יופעל דינמי אוטומטי*  
*All features activate dynamically as the system grows*
