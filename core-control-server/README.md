# 🚀 ALGO-REPLIT Core Control Server

**Complete self-hosted IDE for AlgoGPT - runs natively in Replit**

## Features

✅ **Web IDE**
- File explorer
- Code editor
- Terminal access (WebSocket)

✅ **Local AI**
- Ollama integration (local models)
- OpenAI fallback (optional)
- No API keys needed for local mode

✅ **Project Management**
- Create projects
- List files
- Execute commands
- Audit logging

✅ **Security**
- Single admin token authentication
- File access sandboxing
- Comprehensive audit trail

## Quick Start

### 1. Install & Start

```bash
bash run.sh
```

This will:
- Install Python dependencies
- Create workspace directory
- Start FastAPI server on port 8000

### 2. Access

- **API**: http://localhost:8000
- **Docs**: http://localhost:8000/docs
- **WebSocket Terminal**: ws://localhost:8000/ws/terminal

### 3. Authenticate

All requests need header:
```
Authorization: Bearer YOUR_ADMIN_TOKEN
```

### 4. Create Project

```bash
curl -X POST http://localhost:8000/api/projects/create \
  -H "Authorization: Bearer your_token" \
  -H "Content-Type: application/json" \
  -d '{"name":"my-project","template":"python"}'
```

## API Endpoints

### Files
- `GET /api/files` - List all files
- `GET /api/files/{path}` - Read file
- `POST /api/files/{path}` - Write file
- `DELETE /api/files/{path}` - Delete file

### Projects
- `GET /api/projects` - List projects
- `POST /api/projects/create` - Create project

### Execution
- `POST /api/run` - Execute shell command

### AI
- `POST /api/ai` - Ask AI question

### Terminal
- `WS /ws/terminal?token=...` - Interactive terminal

### Audit
- `GET /api/audit` - View audit log

## Environment Variables

```bash
ADMIN_TOKEN=your_secure_token
ALGO_API_URL=http://localhost:5000
ALGO_API_TOKEN=your_token
OPENAI_API_KEY=sk-...  # Optional
AUTOPILOT_POLL_INTERVAL=20
```

## File Structure

```
core-control-server/
├── app/
│   ├── main.py              # FastAPI app
│   ├── auth.py              # Authentication
│   ├── file_manager.py      # File operations
│   ├── exec_manager.py      # Command execution
│   ├── websocket_manager.py # WebSocket terminal
│   ├── ai_router.py         # AI integration
│   ├── autopilot.py         # AlgoGPT integration
│   ├── audit.py             # Audit logging
│   └── settings.py          # Configuration
├── requirements.txt         # Dependencies
├── run.sh                   # Start script
├── .env.example            # Environment template
└── README.md               # This file
```

## Security

⚠️ **Important**

- Change `ADMIN_TOKEN` before production use
- Use strong, random tokens
- All requests require authentication
- File access is sandboxed to `/workspaces`

## AI Integration

### Local (Ollama)

No API keys needed:

```bash
# Install Ollama
curl https://ollama.ai/install.sh | sh

# Pull model
ollama pull llama2

# Serve
ollama serve
```

Then use AI:
```bash
curl -X POST http://localhost:8000/api/ai \
  -H "Authorization: Bearer token" \
  -d '{"prompt":"Hello"}'
```

### Remote (OpenAI)

Set `OPENAI_API_KEY` in `.env` to enable fallback.

## Auto-Pilot Integration

Connect to AlgoGPT trading system:

```bash
ALGO_API_URL=http://your-algogpt-server
ALGO_API_TOKEN=your-token
```

Server will poll for trade signals every 20 seconds and execute them.

## Troubleshooting

### Port 8000 already in use

```bash
# Find process
lsof -i :8000

# Kill it
kill -9 <PID>
```

### Dependencies not installing

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### WebSocket connection refused

- Check token is correct
- Ensure server is running
- Check firewall

## Development

### Adding endpoints

Edit `app/main.py`:

```python
@app.get("/api/custom")
async def custom_endpoint(request: Request):
    verify_admin(request, admin_token)
    # Your code here
    return {"status": "ok"}
```

### Adding modules

Create file in `app/` and import in `main.py`.

## Deployment

### Replit (Native)
Just run: `bash run.sh`

### Docker
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["bash", "run.sh"]
```

### Render/Heroku
Set `ADMIN_TOKEN` in environment variables.

## License

Built for AlgoGPT trading platform.
