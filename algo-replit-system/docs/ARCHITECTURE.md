# ALGO-REPLIT Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                  ALGO-REPLIT v1.0                       │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  React UI    │  │  AI Chat     │  │  File Editor │  │
│  │  (Port 5173) │  │  (Ollama)    │  │  (Monaco)    │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         └──────────────────┼──────────────────┘         │
│                            │ WebSocket & HTTP           │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  FastAPI Core Control Server (Port 8001)        │   │
│  │  ├─ Project Manager                             │   │
│  │  ├─ File System Manager (Sandboxed)             │   │
│  │  ├─ Process Manager                             │   │
│  │  ├─ WebSocket Logs Streamer                     │   │
│  │  ├─ Backup Manager                              │   │
│  │  ├─ Scale Manager                               │   │
│  │  ├─ Safety Manager                              │   │
│  │  ├─ AI Agent Router                             │   │
│  │  └─ AlgoGPT Integration Router                  │   │
│  └──────────────┬───────────────────────────────────┘   │
│                 │                                        │
├─────────────────┼────────────────────────────────────────┤
│                 │ Services Layer                        │
│  ┌──────────────┴─────────────┬──────────────┐          │
│  │                            │              │          │
│  ▼                            ▼              ▼          │
│ Redis                    Ollama           PostgreSQL    │
│ (Cache/Session)        (Local AI)        (Optional)     │
│ (Port 6379)           (Port 11434)        (Port 5432)   │
│                                                         │
├─────────────────────────────────────────────────────────┤
│               Workspaces & AlgoGPT Integration          │
│  /workspaces/         /backups/          /algogpt/      │
│  ├─ project1/         ├─ backup_*        ├─ src/       │
│  ├─ project2/         └─ restore_*       ├─ routes/    │
│  └─ projectN/                            └─ workers/   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Frontend (React + Vite)

**File**: `frontend/src/App.jsx`

**Components**:
- FileExplorer - project file tree navigation
- CodeEditor - Monaco editor integration
- Terminal - WebSocket-based terminal
- AIChat - Ollama chat interface
- ProjectManager - CRUD operations for projects
- SystemStatus - CPU, memory, resource monitoring

**Tech Stack**:
- React 18
- Vite (dev server on :5173)
- Monaco Editor (code editing)
- XTerm.js (terminal emulation)
- Tailwind CSS (styling)

### 2. Backend (FastAPI)

**File**: `backend/core_control_server.py`

**Features**:
- WebSocket support for real-time logs
- Async/await for concurrent operations
- JWT authentication (admin token)
- File system sandboxing
- Process spawning and management
- Redis integration for caching
- CORS enabled for frontend

**Endpoints**:
- `/health` - System health with resource monitoring
- `/status` - Full system status
- `/projects/*` - Project CRUD operations
- `/files/*` - File read/write operations
- `/services/*` - Process management
- `/ws/logs/*` - WebSocket log streaming
- `/algogpt/*` - AlgoGPT integration
- `/backup/*` - Backup/restore operations
- `/emergency/*` - Safety controls
- `/audit/logs` - Audit trail

### 3. Ollama AI Integration

**File**: `backend/ollama_ai_agent.py`

**Capabilities**:
- Code generation from prompts
- Code modification with instructions
- Error explanation and debugging
- Project scaffolding
- Chat interface with context

**Models**:
- llama2 (general purpose)
- mistral (fast, lightweight)
- codellama (code-specific)

### 4. Backup Manager

**File**: `backend/backup_manager.py`

**Features**:
- Automatic nightly backups (configurable)
- 7-day rolling retention window
- Compress/decompress support
- Safe restore with automatic backup
- Export to zip/tar.gz
- Metadata tracking

### 5. Scale Manager

**File**: `backend/scale_manager.py`

**Dormant Features**:
- Multi-user isolation (toggle: `ENABLE_SCALE_MODE`)
- Load balancing (auto-activates on CPU >80%)
- Multi-node replication (ready for horizontal scaling)
- API isolation per user
- Wallet separation
- Permission tier enforcement

### 6. Safety Manager

**File**: `backend/safety_manager.py`

**Security Features**:
- Audit logging (every action tracked)
- Safety level enforcement
- Emergency freeze (stop all operations)
- Confirmation gates for critical ops
- Watermarking on agent actions
- Denial of trading capabilities

### 7. AlgoGPT Integration

**File**: `backend/algogpt_integration.py`

**Capabilities**:
- Read AlgoGPT files
- Write code changes
- Run unit tests
- Apply patches (with approval)
- Get project statistics
- Access configuration files

## Data Flow

### Creating a Project

```
User Input → React UI
    ↓
HTTP POST /projects/create
    ↓
FastAPI Router → Core Control Server
    ↓
Project Manager (creates directories)
    ↓
Workspace (/workspaces/project_name/)
    ↓
Metadata saved (project.json)
    ↓
Redis audit log
    ↓
Response to UI
```

### Running a Service

```
User clicks "Run"
    ↓
HTTP POST /services/start
    ↓
Process Manager (subprocess.Popen)
    ↓
Service spawned in project directory
    ↓
WebSocket connection established
    ↓
Logs streamed to terminal in real-time
    ↓
User sees live output
```

### Code Editing Flow

```
User edits file in Monaco
    ↓
User clicks Save
    ↓
HTTP POST /files/write
    ↓
File System Manager (security check)
    ↓
Write to disk
    ↓
Redis audit log
    ↓
Confirmation to UI
```

### AI Code Generation

```
User enters prompt
    ↓
HTTP POST /ai/generate
    ↓
Ollama AI Agent (local inference)
    ↓
llama2/mistral model processes
    ↓
Generated code returned
    ↓
Display in editor
    ↓
User applies to file
```

## Security Model

### Authentication
- Single admin user (production: strong token)
- Token required on all requests
- No password authentication (admin-only)

### Authorization
- Admin token = full access
- Invalid token = 401 Unauthorized
- Single-user model (future: per-user permissions)

### File Access
- All paths validated against `WORKSPACES_ROOT`
- Cannot access parent directories
- Symbolic link restrictions
- Deny by default, allow explicitly

### Process Isolation
- Each project has isolated directory
- Processes run in project context
- Resource limits (future: cgroups)
- No cross-project access

### Audit Trail
- Every action logged with timestamp
- User identity tracked
- Action details recorded
- Immutable audit log in Redis

## Scaling Strategy

### Current (Single-User)
- All services on one machine
- Single process per service type
- Dormant multi-user code (no overhead)

### Scale Trigger Conditions
- CPU > 80% for 5+ minutes
- Memory > 85% sustained
- Request queue > 50 items
- Multiple projects running simultaneously

### When Scaled (Manual Toggle)
```bash
ENABLE_SCALE_MODE=true
```

**Activated**:
- Multi-user API isolation
- Wallet separation database tables
- Load balancer configuration
- Multi-node replication setup
- Profit-share automation
- Permission tier enforcement

### Future Expansion Path
1. **Phase 1**: Single machine, single user (NOW)
2. **Phase 2**: Single machine, multi-user (ENABLE_SCALE_MODE=true)
3. **Phase 3**: Multi-machine, multi-user (Kubernetes deployment)
4. **Phase 4**: Global distribution (CDN, regional servers)

## Docker Architecture

```
┌─────────────────────────────────┐
│    Docker Compose Network       │
├─────────────────────────────────┤
│                                 │
│  ┌──────────────────────────┐   │
│  │  core-control-server     │   │
│  │  ├─ FastAPI + Uvicorn    │   │
│  │  ├─ Port 8001 (API)      │   │
│  │  ├─ Port 5173 (Frontend) │   │
│  │  └─ Volumes: /workspaces │   │
│  │           /backups       │   │
│  │           /algogpt (RO)  │   │
│  └──────────────────────────┘   │
│           ↕                      │
│  ┌──────────────────────────┐   │
│  │  Redis                   │   │
│  │  ├─ Cache               │   │
│  │  ├─ Session Store       │   │
│  │  └─ Audit Log           │   │
│  └──────────────────────────┘   │
│           ↕                      │
│  ┌──────────────────────────┐   │
│  │  PostgreSQL              │   │
│  │  ├─ Project metadata     │   │
│  │  ├─ User data (future)   │   │
│  │  └─ Wallet records       │   │
│  └──────────────────────────┘   │
│           ↕                      │
│  ┌──────────────────────────┐   │
│  │  Ollama                  │   │
│  │  ├─ llama2              │   │
│  │  ├─ mistral             │   │
│  │  └─ codellama           │   │
│  └──────────────────────────┘   │
│                                 │
└─────────────────────────────────┘
```

## Performance Characteristics

### Latency
- API response: <100ms (local)
- File I/O: <50ms (SSD)
- AI inference: 2-10s (depending on model)
- WebSocket: <10ms round trip

### Throughput
- Max concurrent projects: 100+ (single machine)
- Max concurrent users: 1 (single-user mode)
- Requests/sec: 1000+ (FastAPI with Uvicorn)
- File operations: 1000+ per second

### Storage
- Minimum: 2GB (code, models, base)
- Per project: 100MB-1GB
- Backups (7-day): 5-10GB
- Ollama models: 5GB per model

## Integration Points

### With AlgoGPT
- Read-only access to project files
- Write access to workspace files
- Test execution
- Patch application (with approval)
- Configuration reading

### With Neon PostgreSQL (optional)
- Project metadata storage
- User data (future)
- Wallet records
- Trade history
- Performance metrics

### With Telegram (future)
- Approval workflows
- Notifications
- Status updates
- Audit events

## Error Handling

### Fail-Closed Design
- Default: deny access
- Explicit: allow specific operations
- Check: validate every action
- Log: track all errors

### Error Recovery
- Automatic retry (with backoff)
- Circuit breaker for service failures
- Graceful degradation
- Error notifications in logs

### Monitoring
- Health check every 30s
- Resource monitoring every minute
- Auto-scale evaluation every minute
- Audit log rotation daily
