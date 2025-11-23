# GIT PUSH Instructions - v10.1 Market Bias Fix

## Commit Message
```
Fix market directional bias: Add EMA tie-breaker to technical fallback + strengthen BTC hard gate (0.5→0)

- Enhanced technical fallback to use EMA20 vs EMA50 alignment as intelligent tie-breaker
- Reduced BTC correlation rejection threshold from 0.5 to 0 (blocks ALL conflicting positions)
- Prevents excessive SHORT trades when BTC is bullish (fixing -1.0 penalty issue)
- System now aligns trade direction with market conditions before execution
```

## Files Changed
1. `workers/gpt_auto_suggest.py` - Lines 1409-1422, Lines 1793-1799
   - Added EMA alignment logic for NEUTRAL trend situations
   - Strengthened BTC hard gate rejection threshold

2. `replit.md` - Added Recent Changes section
   - Documented the fix in v10.1

## How to Push

Run these commands in your terminal:

```bash
cd /home/runner/workspace

# Check status
git status

# Add changes
git add workers/gpt_auto_suggest.py replit.md

# Commit
git commit -m "Fix market directional bias: Add EMA tie-breaker to technical fallback + strengthen BTC hard gate (0.5→0)

- Enhanced technical fallback to use EMA20 vs EMA50 alignment as intelligent tie-breaker
- Reduced BTC correlation rejection threshold from 0.5 to 0 (blocks ALL conflicting positions)
- Prevents excessive SHORT trades when BTC is bullish (fixing -1.0 penalty issue)
- System now aligns trade direction with market conditions before execution"

# Push to origin
git push origin main
```

Or simpler version:

```bash
cd /home/runner/workspace
git add workers/gpt_auto_suggest.py replit.md
git commit -m "Fix market directional bias: Add EMA tie-breaker + strengthen BTC hard gate"
git push origin main
```

## What This Does
✅ Commits all changes from the market bias fix
✅ Pushes to GitHub main branch
✅ Updates remote repository with v10.1 improvements

## Summary of Changes
- **Technical Fallback**: Now uses EMA alignment (EMA20 > EMA50 = LONG) when market trend is NEUTRAL
- **BTC Hard Gate**: Any BTC penalty > 0 now blocks conflicting positions (was > 0.5)
- **Result**: System avoids SHORT trades during BULLISH BTC conditions, fixing the -1.0 penalty issue
