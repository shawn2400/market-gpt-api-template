# 🔌 Integration Guide — AlgoGPT External Brain

## Add to main.py

In your main FastAPI app (`main.py`):

```python
from fastapi import FastAPI
from routes.external_routes import router as external_router

app = FastAPI()

# Include external brain routes
app.include_router(external_router)
```

## Dashboard Integration

The React dashboard will connect to these endpoints:

```javascript
const API_BASE = "http://localhost:5000/external";

// Get all bot status
fetch(`${API_BASE}/status`)

// Control a bot
fetch(`${API_BASE}/control/cryptohopper/on`, { method: "POST" })

// Get market analysis
fetch(`${API_BASE}/analyze`)

// Get bot scores
fetch(`${API_BASE}/scores`)
```

## With Existing Systems

**Current Status**: ✅ All 9 AlgoGPT workflows running
- AlgoGPT Server — OK
- Auto Scanner — OK
- Position Monitor — OK
- Fills Watcher — OK
- etc.

**Integration Impact**: ZERO
- New system runs in parallel
- No changes to existing code
- Can be toggled ON/OFF per bot
- Failsafe: if external system down, AlgoGPT continues alone

## Auto-Detection Flow

```
1. User has FREE plan in Cryptohopper
   → System uses LIMITED_SCANS = 30

2. User upgrades to PAID plan
   → Set PAID_CRYPTOHOPPER=1 in env
   → System auto-detects
   → Now uses FULL_SCANS = 300
   → No manual restart needed
```

## Testing

```bash
# Validate syntax
python3 -m py_compile external/*.py algo_core/*.py routes/external_routes.py

# Run test suite
pytest tests/ -v

# Check endpoints
curl http://localhost:5000/external/status
```

## Deployment

1. Push code to git
2. External brain loads automatically
3. All 6 bots available immediately
4. Dashboard ready for UI

**No additional infrastructure needed** — everything async, efficient.

---

Ready to integrate? 🚀
