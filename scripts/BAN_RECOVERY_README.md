# 🚨 Binance IP Ban Recovery System

## Overview
Emergency kill-switch system to recover from Binance IP bans caused by excessive REST API calls.

## Problem
When workers poll Binance REST API too frequently, the IP gets banned for 2-3 hours. Each new request extends the ban timer.

## Solution - 3-Phase Recovery

### Phase 1: Emergency Kill-Switch (IMMEDIATE)
**Status:** ✅ ACTIVE

All 9 workers are disabled via `EMERGENCY_KILL_SWITCH=1` in `render.yaml`.

**What's running:**
- ✅ API Server (Gunicorn + FastAPI)
- ✅ WebSocket UserStream (no rate limits)
- ❌ All 9 workers (disabled to stop REST polling)

**Expected result:**
- Zero REST API calls to Binance
- Ban timer stops extending
- WebSocket provides live updates (positions, fills, orders)

### Phase 2: Wait for Ban Clearance (3+ HOURS)
**Cooldown period:** Minimum 3 hours of complete silence

**During cooldown:**
1. No worker restarts
2. No manual API calls
3. No time sync attempts
4. WebSocket remains active (safe)

**Check ban status:**
```bash
python scripts/check_ban_status.py
```

Exit codes:
- `0` = Ban cleared ✅
- `1` = Still banned ⚠️ (wait 60 more minutes)
- `2` = Error/Unknown

### Phase 3: Safe-Boot Mode (AFTER BAN CLEARED)

#### Step 1: Disable Kill-Switch
Edit `render.yaml`:
```yaml
- key: EMERGENCY_KILL_SWITCH
  value: 0  # Changed from 1
- key: BAN_RECOVERY_MODE
  value: 0  # Changed from 1
```

#### Step 2: Push to GitHub
```bash
git add render.yaml
git commit -m "🚀 Disable kill-switch - ban cleared"
git push origin main
```

GitHub Actions will auto-deploy to Render with workers enabled.

#### Step 3: Staggered Startup (Automatic)
Workers start with 12-second delays to prevent burst:

1. Position Monitor (0s)
2. Fills Watcher (12s)
3. Insurance Monitor (24s)
4. Auto Health Monitor (36s)
5. Auto Optimization (48s)
6. Auto Scanner (60s)
7. Quantum TOP 50 (72s)
8. Sentinel Security (84s)
9. Telegram Digest (96s)

**Total startup time:** ~2 minutes

## Auto-Ban-Shield (Permanent Protection)

### REST Rate Limiting
- **Max:** 40 requests/min (well below Binance 2400/min limit)
- **Throttling:** Automatic delays between requests
- **Fail-safe:** Auto-pause 2h if burst detected

### WebSocket-First Strategy
- All position/balance/order updates via WebSocket
- REST API only for:
  - Symbol scanning (throttled)
  - Initial data fetch
  - Manual operations

## Current Status

**As of:** November 17, 2025 14:34 UTC

- 🚨 Kill-Switch: **ACTIVE**
- 📊 Workers: **0/9 running**
- 🔌 WebSocket: **ACTIVE**
- ⏰ Ban clears: **~16:18 IST** (estimated)

## Troubleshooting

### Ban still active after 3 hours?
```bash
# Check ban status
python scripts/check_ban_status.py

# If still banned, wait another hour
# Each failed check does NOT extend ban
```

### Workers not starting after re-enable?
```bash
# Check Render logs
# Verify EMERGENCY_KILL_SWITCH=0 in dashboard
# Manually trigger deployment if needed
```

### New ban after Safe-Boot?
```bash
# Immediately re-enable kill-switch
# Set EMERGENCY_KILL_SWITCH=1
# Push to GitHub
# Contact support - possible config issue
```

## Prevention (Long-Term)

1. **WebSocket integration** for all workers
2. **Respect rate limits** - 40 req/min max
3. **Batch operations** - group API calls
4. **Cache aggressively** - reduce redundant calls
5. **Monitor usage** - alert before hitting limits

## Files Modified

- `render.yaml` - Added kill-switch flags
- `start.sh` - Added kill-switch logic
- `scripts/check_ban_status.py` - Ban checker
- `scripts/safe_boot_workers.sh` - Staggered startup
- `scripts/BAN_RECOVERY_README.md` - This file

## Contact

If ban persists >6 hours, contact Binance support with:
- IP address: `74.220.51.250`
- Timestamp of ban
- Mitigation steps taken
