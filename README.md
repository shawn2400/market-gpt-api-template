# 🚀 AlgoGPT — Multi-AI Autonomous Trading Platform

```
    ╔═══════════════════════════════════════════════════════════════╗
    ║   █████╗ ██╗      ██████╗  ██████╗  ██████╗ ██████╗ ████████╗ ║
    ║  ██╔══██╗██║     ██╔════╝ ██╔═══██╗██╔════╝ ██╔══██╗╚══██╔══╝ ║
    ║  ███████║██║     ██║  ███╗██║   ██║██║  ███╗██████╔╝   ██║    ║
    ║  ██╔══██║██║     ██║   ██║██║   ██║██║   ██║██╔═══╝    ██║    ║
    ║  ██║  ██║███████╗╚██████╔╝╚██████╔╝╚██████╔╝██║        ██║    ║
    ║  ╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝  ╚═════╝ ╚═╝        ╚═╝    ║
    ║                                                                 ║
    ║        🤖 Autonomous AI-Powered Futures Trading Engine         ║
    ╚═══════════════════════════════════════════════════════════════╝
```

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![GPT-5](https://img.shields.io/badge/GPT--5-2025--08--07-412991?style=for-the-badge&logo=openai&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Neon-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![License](https://img.shields.io/badge/License-Private-red?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Live%2024/7-success?style=for-the-badge)

**Version:** `9.1.0` | **AI Brains:** 3 (Cost-Optimized: DeepSeek+Grok+Gemini) | **Workers:** 10 | **Strategies:** 7 | **Markets:** 534 | **Cost Savings:** 90%

[🎯 Features](#-features) • [🧠 AI Brains](#-ai-brains-multi-model-consensus) • [⚙️ Workers](#️-workers-background-processes) • [📊 Strategies](#-trading-strategies) • [🔐 Security](#-security-hmac-signature)

</div>

---

## 🌟 Overview | סקירה כללית

**AlgoGPT v9.1** היא פלטפורמת מסחר אלגוריתמי אוטונומית המבוססת על **3 מודלי AI זולים** (DeepSeek + Grok + Gemini) שפועלים במערך קונצנזוס מהיר **לקבלת החלטות מסחר**. המערכת פועלת 24/7 על Binance Futures, מנתחת באופן רציף 534 שווקים שונים, וסורקת **50 symbols בכל סבב** (x5 שיפור כיסוי שוק). **הפחתת עלויות: 90%** (הסרת GPT-5 + Claude מקבלת החלטות מסחר).

**AlgoGPT v9.1** is a cutting-edge autonomous algorithmic trading platform powered by **3 cost-optimized AI brains for trade decisions** (DeepSeek + Grok + Gemini). Removed expensive providers from trade consensus (GPT-5 $15/M, Claude $3/M → `ENABLE_OPENAI=0`). It runs 24/7 on Binance Futures, continuously analyzing 534 markets across multiple timeframes, scanning **50 symbols per cycle** (5x market coverage improvement), and executes 4-10 high-quality trades daily with regime-adaptive dynamic risk management. **Cost Reduction: 90%** by disabling GPT-5 and Claude for trade decisions.

### 🎯 Core Capabilities | יכולות ליבה

- ⚡ **24/7 Automated Trading** — מסחר אוטומטי מלא עם ביצוע מיידי (LIMIT + MARKET)
- 🧠 **3-Brain AI Consensus (Cost-Optimized)** — DeepSeek + Grok + Gemini | **90% cost reduction** (removed GPT-5 + Claude)
- 📊 **534 Markets Scanning (50/cycle)** — סריקה של 50 symbols בכל סבב (x5 שיפור כיסוי)
- 🛡️ **Multi-Layer Protection System** — SL+TP validation + Post-entry verification + Continuous monitoring
- 🔄 **7 Trading Strategies** — Mean-Reversion, Scalping, Range-Bounce, Trend-Following, Breakout, GRID, SPOT
- 📈 **Dynamic SL/TP System** — ATR-based Stop Loss, RR-based Take Profit, Regime-adaptive parameters
- 🎯 **Smart Filter (Quality 6.0)** — Stage 2 gating blocks low-quality trades before AI spend
- 🔐 **HMAC Signature Security** — חתימה דינמית לכל בקשה + anti-replay protection
- 💰 **Low Daily Cost** — Only cheap AI brains (DeepSeek $0.14/M, Grok free, Gemini 50 calls/day free)

---

## 🧠 AI Brains (Cost-Optimized Consensus)

**AlgoGPT v9.1** uses **3 COST-OPTIMIZED AI BRAINS** for maximum efficiency. By **removing expensive providers** (GPT-5, Claude), we achieve **90% cost reduction** while maintaining high-quality trade decisions through fast triple-brain consensus.

### 💎 Cost Optimization Strategy

**Disabled for Trade Decisions** (`ENABLE_OPENAI=0` in `ai_trade_scorer.py`):
- ❌ GPT-5: $15/M tokens (~$300-400/month) - **DISABLED FOR TRADING**
- ❌ Claude Sonnet 3.5: $3/M tokens (~$50-100/month) - **REMOVED ENTIRELY**

**Active for Trade Decisions:**
- ✅ DeepSeek: $0.14/M tokens (~$10-20/month)
- ✅ Grok (XAI): Free tier (generous limits)
- ✅ Gemini 2 Pro: 50 calls/day free tier (fallback/tiebreaker)

**GPT-5 Orchestrator:**
- ⚠️ GPT-5 still runs as a monitoring worker (`gpt5_orchestrator.py`) for system-level analysis
- NOT used for individual trade decisions (disabled in consensus)
- Low usage: every 30 minutes = ~$5-10/month

**Result: 90% cost reduction on trade decision-making!**

### 🧠 AI Brain #1: DeepSeek
- **Model**: `deepseek-chat`
- **Role**: Primary Analyst - ניתוח שוק עמוק
- **Temperature**: 0.7
- **Max Tokens**: 300
- **Cost**: $0.14/M tokens (ultra-cheap!)
- **Status**: ✅ Active
- **Performance**: Excellent pattern recognition, fast responses

### ⚡ AI Brain #2: Grok (XAI)
- **Model**: `grok-2-latest`
- **Role**: Contrarian Validator - ולידציה קונטרריאנית
- **Temperature**: 0.8
- **Max Tokens**: 300
- **Cost**: FREE (generous tier)
- **Status**: ✅ Active
- **Performance**: Strong contrarian analysis, real-time insights

### 🌟 AI Brain #3: Gemini 2 Pro (Google)
- **Model**: `gemini-2.0-flash-exp`
- **Role**: Tiebreaker & Fallback - פותר תיקו וגיבוי
- **Temperature**: 0.7
- **Max Tokens**: 300
- **Cost**: FREE (50 calls/day limit)
- **Status**: ✅ Active (fallback mode)
- **Performance**: Fast multi-modal reasoning, used as tiebreaker

### 🗳️ Fast Triple-Brain Consensus (v9.1)

```python
# Optimized Voting Flow:
1. Scout generates trade proposal (MI + SO scores)
2. All 3 AI brains analyze proposal independently:
   - DeepSeek (primary analyst)
   - Grok/XAI (contrarian validator)
   - Gemini (tiebreaker/fallback)
3. Each brain votes APPROVE/REJECT with score (0-10)
4. Consensus decision:
   - ≥2/3 APPROVE → ✅ Execute Trade
   - <2/3 APPROVE → ❌ Reject Proposal
5. Final score = median(all_brain_scores)
```

**Example Consensus (v9.1):**
```
DeepSeek:       APPROVE (7.5/10) ✅
Grok:           APPROVE (8.1/10) ✅
Gemini:         REJECT  (5.8/10) ❌

Result: 2/3 APPROVE (67%) → ✅ EXECUTE
Final Score: 7.5/10 (median)
Cost: $0.0002 (vs $0.05 with 5 brains including GPT-5+Claude)
Speed: 2-3 seconds (vs 5-7 seconds)
```

**Smart Filter Integration:**
- Stage 1: Volume spike validation (>1.5x)
- Stage 2: Quality threshold (≥6.0/10) **← BLOCKS before AI spend**
- Stage 3: AI consensus (3 cheap brains)
- Result: **90% cost reduction** by removing expensive providers

---

## 🛡️ Multi-Layer Protection System

**AlgoGPT v9.1** implements a **Multi-Layer Protection System** to minimize unprotected positions. While we strive for maximum SL+TP coverage, the system uses validation + verification + continuous monitoring.

### 🔹 Layer 1: SL/TP Configuration Validation
**When**: During trade proposal generation
**File**: `utils/auto_executor.py`, `utils/trade_execution_core.py`

Trade proposals include SL+TP configuration:
```python
# Configuration in proposal:
1. Stop Loss (SL) calculated using ATR
2. Take Profit (TP) calculated using RR ratio
3. SL price validated (not too tight, not too wide)
4. TP price ensures minimum RR ratio
5. Parameters adapt to market regime
```

**Protection:**
- ATR-based SL calculation (0.5-4.0 ATR multiplier)
- RR-based TP calculation (1.0-5.0 RR ratio)
- Dynamic adjustment based on market regime
- Regime-specific parameters (TRENDING/CHOPPY/VOLATILE/SIDEWAYS)

### 🔹 Layer 2: Post-Entry Verification
**When**: After position entry (monitored by Position Monitor)
**File**: `utils/emergency_protection.py`, `workers/position_monitor.py`

After position is opened, system verifies SL/TP orders exist:
```python
# Verification flow:
1. Position entry confirmed (positionAmt ≠ 0)
2. Fetch all open orders from Binance
3. Check for STOP_MARKET order (SL)
4. Check for TAKE_PROFIT_MARKET order (TP)

If SL or TP missing:
→ Emergency market close immediately
→ Circuit breaker activation
→ Critical Telegram alert
→ System pause (PAUSE_AUTO_RUN=1)
```

**Protection:**
- Detects failed SL/TP order placement
- Immediate emergency exit if protection missing
- Prevents runaway losses

### 🔹 Layer 3: Continuous Monitoring (Every 30 seconds)
**When**: Every 30 seconds while position is open
**File**: `workers/position_monitor.py`

Position Monitor continuously checks all open positions:
```python
# Monitoring flow:
1. Fetch all open positions from Binance
2. For each position with positionAmt ≠ 0:
   a. Get all open orders
   b. Verify STOP_MARKET exists
   c. Verify TAKE_PROFIT_MARKET exists
3. If position is unprotected:
   → Emergency market close
   → Circuit breaker trigger
   → Critical alert

Circuit Breaker:
- Triggered when 2+ unprotected positions detected within 1 hour
- Sets PAUSE_AUTO_RUN=1 (stops new trades)
- Sends critical Telegram alert
- Requires manual review before resuming
```

**Protection:**
- Continuous safety net for all positions
- Catches edge cases (exchange errors, network failures, order rejections)
- Auto-pause prevents cascading failures
- 30-second check interval ensures rapid detection

### 📊 Enhanced Logging & Telemetry

Every order event is logged with full details:
- Order placed (type, price, quantity, timestamp)
- Order filled (execution price, fees, slippage)
- Order cancelled (reason, timestamp)
- Order expired (reason, timestamp)

**File**: `utils/auto_executor.py`, `utils/trade_execution_core.py`

This enables:
- Complete forensic analysis of every trade
- Root cause analysis of protection failures
- Performance optimization (slippage, fees, timing)

### 🚨 Emergency Close Function

Direct market close bypassing normal order flow:
```python
emergency_close_position(symbol, position_amt)
→ Immediate MARKET order to close
→ Skips all queues and validations
→ Used ONLY for unprotected positions
```

**File**: `utils/emergency_protection.py`

---

## ⚙️ Workers (Background Processes)

AlgoGPT מריצה **10 workers** בפרלל, כל אחד אחראי על תפקיד ספציפי במערכת.

### 🌐 Worker #1: AlgoGPT Server
- **File**: `main.py`
- **Command**: `gunicorn -c gunicorn_conf.py main:app`
- **Port**: 5000 (webview)
- **Description**: FastAPI server ראשי - מטפל ב-API requests, webhooks, ו-UI dashboard
- **Environment Variables**:
  - `PORT=5000`
  - `EXECUTE_TRADES=1`
  - `APPROVAL_ENABLED=0` (auto-execute)
  - `ENABLE_MULTI_AI_CONSENSUS=1`

### 🏥 Worker #2: Auto Health Monitor
- **File**: `workers/auto_health_monitor.py`
- **Command**: `python workers/auto_health_monitor.py`
- **Port**: None
- **Description**: בודק health של המערכת כל 30 שניות, שולח התראות CRITICAL אחרי 5 כשלונות רצופים + 15 דקות cooldown
- **Environment Variables**:
  - `HEALTH_CHECK_INTERVAL=30`
  - `AUTO_FIX_ENABLE=1`
  - `TELEGRAM_SEND_ENABLE=1`

### 📡 Worker #3: Auto Scanner (v9.1 - Enhanced)
- **File**: `workers/gpt_auto_suggest.py`
- **Command**: `python workers/gpt_auto_suggest.py`
- **Port**: None
- **Description**: סורק **50 symbols בכל סבב** (x5 improvement!), מציע trades באמצעות 7 אסטרטגיות + 3 AI brains consensus (DeepSeek + Grok + Gemini)
- **Two-Tier Strategy**:
  - **Tier 1**: Scans symbols with quality 4-10 (market breadth)
  - **Tier 2**: Smart Filter blocks <6.0 quality before AI spend
- **Environment Variables**:
  - `POOL_PER_CYCLE=50` (was 10)
  - `SUGGEST_FUTURES=1`
  - `SUGGEST_SPOT=1`
  - `SUGGEST_GRID=1` ✅ **NOW ENABLED**
  - `AUTO_RUN=1`
  - `ENABLE_DEEPSEEK=1`, `ENABLE_XAI=1`, `ENABLE_GEMINI=1`
  - `ENABLE_OPENAI=0` (cost optimization)

### 📅 Worker #4: Daily Meeting 00:00
- **File**: `workers/daily_meeting.py`
- **Command**: `python workers/daily_meeting.py`
- **Port**: None
- **Description**: דוח יומי ב-00:00 UTC עם PnL, Win Rate, סיכום trades (70% עברית, 30% אנגלית)
- **Environment Variables**: None

### 📋 Worker #5: Fills Watcher
- **File**: `workers/fills_watcher.py`
- **Command**: `python workers/fills_watcher.py`
- **Port**: None
- **Description**: עוקב אחרי orders שמולאו (FILLED) כל 15 שניות, שולח התראות Telegram
- **Environment Variables**:
  - `FILLS_WATCH_ENABLE=1`
  - `FILLS_WATCH_INTERVAL_SEC=15`

### 🧠 Worker #6: GPT-5 Central Brain (Monitoring Only)
- **File**: `workers/gpt5_orchestrator.py`
- **Command**: `python workers/gpt5_orchestrator.py`
- **Port**: None
- **Description**: System monitoring and strategic oversight (NOT used for trade decisions)
- **Note**: ⚠️ GPT-5 is **disabled for trade scoring** (`ENABLE_OPENAI=0`) to reduce costs. This worker only provides periodic system analysis.
- **Environment Variables**:
  - `GPT5_ORCHESTRATOR_ENABLED=1` (monitoring mode)
  - `ORCHESTRATOR_INTERVAL_SEC=1800`

### 📊 Worker #7: Position Monitor
- **File**: `workers/position_monitor.py`
- **Command**: `python workers/position_monitor.py`
- **Port**: None
- **Description**: עוקב אחרי positions פתוחות כל 30 דקות, שולח דוחות PnL, **מבטל אוטומטית את כל ה-orders כש-position נסגר** (תוקן!)
- **Environment Variables**:
  - `ENABLE_POSITION_MONITOR=1`
  - `POSITION_REPORT_INTERVAL_SEC=1800`
  - `POSITION_ALERT_LEVEL=all`

### 🔒 Worker #8: Sentinel Security
- **File**: `workers/sentinel_security.py`
- **Command**: `python workers/sentinel_security.py`
- **Port**: None
- **Description**: מעקב אבטחה ו-anomaly detection
- **Environment Variables**:
  - `SENTINEL_ENABLED=1`
  - `SENTINEL_ALERT_LEVEL=critical`

---

## 📈 Dynamic SL/TP System (ATR-Based)

**AlgoGPT v9.1** uses **100% dynamic Stop Loss and Take Profit** calculations that adapt to market volatility and regime in real-time. NO HARDCODED VALUES.

### 🎯 Dynamic Stop Loss (ATR-Based)

Stop Loss distance is calculated using ATR (Average True Range) multiplier:

```python
# SL Calculation:
SL_distance = ATR(14) × SL_multiplier

# SL Multiplier Ranges (regime-adaptive):
TRENDING:   0.8 - 1.2 ATR  (wider stops for trends)
CHOPPY:     0.5 - 0.8 ATR  (tighter stops for chop)
VOLATILE:   1.2 - 2.0 ATR  (wide stops for volatility)
SIDEWAYS:   0.6 - 0.9 ATR  (moderate stops for range)

# Final SL Price:
LONG:  entry_price - SL_distance
SHORT: entry_price + SL_distance
```

**File**: `utils/dynamic_sltp_manager.py`

**Benefits:**
- Adapts to market volatility (high ATR → wider stops)
- Prevents premature stop-outs in volatile markets
- Tightens stops in calm markets to preserve capital
- AI chooses exact multiplier within safety ranges

### 💰 Dynamic Take Profit (RR-Based)

Take Profit is calculated using Risk/Reward (RR) ratio:

```python
# TP Calculation:
TP_distance = SL_distance × RR_ratio

# RR Ratio Ranges (regime-adaptive):
TRENDING:   1.8 - 3.0 RR  (ride the trend)
CHOPPY:     1.2 - 1.5 RR  (quick exits)
VOLATILE:   1.5 - 2.5 RR  (balanced)
SIDEWAYS:   1.3 - 1.8 RR  (range targets)

# Minimum RR Requirements:
Mean-Reversion:   1.05 RR
Scalping:         1.2 RR
Range-Bounce:     1.3 RR
Trend-Following:  1.8 RR
Breakout:         2.0 RR

# Final TP Price:
LONG:  entry_price + TP_distance
SHORT: entry_price - TP_distance
```

**File**: `utils/dynamic_sltp_manager.py`

**Benefits:**
- Ensures positive expected value (RR ≥1.0)
- Adapts TP targets to market regime
- Higher RR in trending markets (let winners run)
- Lower RR in choppy markets (take profits quickly)

### 🔄 Regime-Adaptive Parameters

AI adjusts SL/TP parameters based on detected market regime:

| Regime | SL ATR | TP RR | Leverage | Strategy Preference |
|--------|---------|--------|----------|---------------------|
| TRENDING | 0.8-1.2 | 1.8-3.0 | 3-8x | Trend-Following, Breakout |
| CHOPPY | 0.5-0.8 | 1.2-1.5 | 5-10x | Mean-Reversion, Scalping |
| VOLATILE | 1.2-2.0 | 1.5-2.5 | 2-5x | Scalping, Range-Bounce |
| SIDEWAYS | 0.6-0.9 | 1.3-1.8 | 4-7x | Range-Bounce, GRID |

**File**: `utils/live_regime_detector.py`, `utils/metabrain/dynamic_protection_manager.py`

### ⚡ Break-Even (BE) Logic

Position moves to break-even when profit threshold is reached:

```python
# BE Trigger (dynamic):
if unrealized_pnl >= (SL_distance × BE_trigger_ratio):
    move_SL_to_break_even()

# BE Trigger Ratios (regime-adaptive):
TRENDING:   0.5 (50% of SL distance)
CHOPPY:     0.3 (30% of SL distance - earlier BE)
VOLATILE:   0.4 (40% of SL distance)
SIDEWAYS:   0.35 (35% of SL distance)
```

**File**: `utils/trade_manager.py`

**Benefits:**
- Locks in profits early
- Removes downside risk once position is profitable
- Earlier BE in choppy markets (protect gains)
- Later BE in trending markets (give room to breathe)

### 📊 Trailing Stop (Optional)

ATR-based trailing stop for trend-following:

```python
# Trailing Stop:
trail_distance = ATR(14) × trail_multiplier

# Trail Multipliers:
TRENDING:   1.0 - 1.5 ATR
VOLATILE:   1.5 - 2.0 ATR

# Activation:
Activates after BE is triggered
Trails price at trail_distance
Never moves backwards (only follows price up)
```

**File**: `utils/trade_manager.py`

**Benefits:**
- Captures extended moves in trending markets
- Dynamic trailing distance adapts to volatility
- Protects profits while allowing upside

---

## 🎯 Smart Filter (Quality 6.0 Threshold)

**AlgoGPT v9.1** uses a **Smart Filter** to block low-quality trades BEFORE expensive AI consensus calls. This achieves **90% cost reduction** by filtering at Stage 2.

### 📊 Two-Tier Scanning Strategy

```python
# Stage 1: Broad Market Scan (min_quality=4)
- Scans 50 symbols per cycle
- Accepts quality scores 4.0 - 10.0
- Volume spike validation (>1.5x avg)
- Technical setup validation
- Result: ~30-40 symbols pass Stage 1

# Stage 2: Smart Filter (quality_threshold=6.0)
- Blocks symbols with quality <6.0
- BEFORE calling expensive AI brains
- Only high-quality symbols proceed
- Result: ~5-10 symbols pass Stage 2

# Stage 3: AI Consensus (2 cheap brains)
- DeepSeek + Grok analyze proposal
- Votes APPROVE/REJECT with scores
- Final decision based on consensus
- Result: ~2-5 trades per cycle
```

**File**: `utils/smart_filter.py`, `workers/gpt_auto_suggest.py`

### ✅ Smart Filter Logic

```python
def smart_filter(symbol_data):
    # Quality Score Calculation:
    quality = calculate_quality_score(
        mi_score,      # Market Intelligence (0-10)
        so_score,      # Scout Opinion (0-10)
        volume_spike,  # Volume ratio
        atr_percentile # Volatility rank
    )
    
    # Gate Decision:
    if quality < 6.0:
        return "BLOCKED"  # No AI spend
    else:
        return "PASS"     # Proceed to AI consensus
```

**Benefits:**
- **90% cost reduction**: Filters before AI calls
- **5x market coverage**: Scan 50 symbols (was 10)
- **Quality maintained**: Only ≥6.0 proceed to AI
- **No quality dilution**: Two-tier ensures high bar

### 📈 Stage 2 Gating Impact

| Metric | Before Filter | After Filter | Improvement |
|--------|---------------|--------------|-------------|
| Symbols Scanned | 10/cycle | 50/cycle | **5x coverage** |
| AI Calls | 10/cycle | 5-10/cycle | **50% reduction** |
| Cost per Cycle | $0.05 | $0.005 | **90% savings** |
| Quality Threshold | 6.0 | 6.0 | **Maintained** |
| Trades per Day | 4-6 | 4-10 | **Market breadth** |

### 🛡️ Safety Ranges

AI has wide safety ranges but Smart Filter ensures baseline quality:

```python
# Wide Safety Ranges (AI freedom):
Quality:  2.0 - 10.0 (AI can suggest anything)
SL ATR:   0.5 - 4.0
TP RR:    1.0 - 5.0
Leverage: 1x - 15x

# Smart Filter Enforcement (Stage 2):
Quality < 6.0 → BLOCKED before AI spend
Quality ≥ 6.0 → Proceed to AI consensus

# Downstream Guardrails (Stage 3+):
- order_sanity.py: Validates order parameters
- leverage_policy.py: Enforces leverage caps
- precision_calculator.py: Calculates exact sizing
```

---

## 📊 Trading Strategies

AlgoGPT משתמשת ב**7 אסטרטגיות מסחר** שונות, כל אחת מותאמת למשטר שוק ספציפי.

### 1️⃣ Mean-Reversion (VWAP-Based)
- **File**: `utils/mean_reversion_strategy.py`
- **When**: CHOPPY markets, range <2%
- **Entry**: VWAP deviation >1.5 ATR
- **SL**: 0.7 ATR
- **TP**: VWAP ± 1.5 ATR
- **MinRR**: 1.05
- **MinQuality**: 5.0
- **MaxLeverage**: 6x

### 2️⃣ Scalping
- **File**: `utils/strategy_orchestrator.py`
- **When**: High volatility, strong momentum
- **Entry**: Quick in/out on 15M candles
- **SL**: 0.4 ATR
- **TP**: 1.2 RR
- **MinRR**: 1.2
- **MinQuality**: 6.0
- **MaxLeverage**: 8x

### 3️⃣ Range-Bounce
- **File**: `utils/strategy_orchestrator.py`
- **When**: Sideways markets, clear S/R levels
- **Entry**: Bounce from support/resistance
- **SL**: 0.5 ATR
- **TP**: 1.3 RR
- **MinRR**: 1.3
- **MinQuality**: 5.5
- **MaxLeverage**: 7x

### 4️⃣ Trend-Following
- **File**: `utils/strategy_orchestrator.py`
- **When**: Strong trends (ADX >25)
- **Entry**: Pullback to EMA21
- **SL**: 1.0 ATR
- **TP**: 2.0 RR
- **MinRR**: 1.8
- **MinQuality**: 6.5
- **MaxLeverage**: 5x

### 5️⃣ Breakout
- **File**: `utils/strategy_orchestrator.py`
- **When**: Consolidation → expansion
- **Entry**: Break of S/R + volume
- **SL**: 0.8 ATR
- **TP**: 2.5 RR
- **MinRR**: 2.0
- **MinQuality**: 7.0
- **MaxLeverage**: 4x

### 6️⃣ GRID Trading
- **File**: `routes/grid.py`
- **When**: Sideways markets, low volatility
- **Entry**: Grid of buy/sell orders
- **SL**: Grid-based
- **TP**: Grid-based
- **MinRR**: 1.1
- **MinQuality**: 4.5
- **MaxLeverage**: 3x

### 7️⃣ SPOT Trading
- **File**: `workers/gpt_auto_suggest.py`
- **When**: Strong uptrends, low risk
- **Entry**: SPOT buy only
- **SL**: None (HODL)
- **TP**: Manual or trailing
- **MinRR**: N/A
- **MinQuality**: 7.5
- **MaxLeverage**: 1x (no leverage)

---

## 🔬 Technical Indicators

AlgoGPT משתמשת ב**12 אינדיקטורים טכניים** לניתוח שוק מקיף:

### 📊 Momentum Indicators
1. **RSI (Relative Strength Index)** - `utils/indicators.py`
   - Period: 14
   - Oversold: <30
   - Overbought: >70

2. **MACD (Moving Average Convergence Divergence)** - `utils/indicators.py`
   - Fast: 12
   - Slow: 26
   - Signal: 9

### 📈 Trend Indicators
3. **EMA (Exponential Moving Average)** - `utils/indicators.py`
   - EMA21 (short-term)
   - EMA50 (medium-term)

4. **ADX (Average Directional Index)** - `utils/indicators.py`
   - Period: 14
   - Strong Trend: >25
   - Weak Trend: <20

### 💥 Volatility Indicators
5. **ATR (Average True Range)** - `utils/indicators.py`
   - Period: 14
   - Used for SL/TP calculation

6. **Bollinger Bands** - `utils/indicators.py`
   - Period: 20
   - Std Dev: 2

### 📊 Volume Indicators
7. **VWAP (Volume Weighted Average Price)** - `utils/indicators_ext.py`
   - Period: 50
   - Mean-reversion anchor

8. **OBV (On-Balance Volume)** - `utils/indicators_ext.py`
   - Cumulative volume

9. **Keltner Channels** - `utils/mean_reversion_strategy.py`
   - Period: 20
   - ATR multiplier: 2.0

### 🎯 Advanced Indicators
10. **QQE (Quantitative Qualitative Estimation)** - `utils/indicators_qqe.py`
    - RSI-based momentum

11. **SMC (Smart Money Concepts)** - `utils/indicators_smc.py`
    - FVG (Fair Value Gaps)
    - Sweeps (Stop Hunt)

12. **Volume** - Real-time Binance volume data

---

## 🌍 API Endpoints

AlgoGPT מספקת **50+ API endpoints** לניהול מסחר, ניטור, ו-automation.

### 🔐 Authentication

**All endpoints** require HMAC signature authentication (except public endpoints).

**Headers Required:**
```http
X-API-Key: Bearer <api_key>
X-Timestamp: <unix_timestamp>
X-Nonce: <random_hex_32>
X-Signature: <hmac_sha256_hex>
Digest: <sha256_base64_body>
```

### 📊 Core Endpoints

#### Health & Status
```http
GET  /health              - Basic health check
GET  /readyz              - Readiness probe
GET  /api/info            - System information
```

#### Market Data
```http
GET  /price/{symbol}            - Latest price
GET  /scan/public-topk          - Top market opportunities
GET  /context/batch             - Batch market context
```

#### Trading
```http
POST /alerts/ingest             - Trade proposal ingestion (HMAC required)
POST /trade/execute             - Manual trade execution
GET  /executor/positions        - Active positions
POST /position-ops/manage-once  - Manage open positions
```

#### AI & Analysis
```http
POST /ai/suggest                - AI trade suggestions
GET  /ai/leaderboard            - AI model performance
GET  /ai/performance            - Detailed AI metrics
```

#### PnL & Reports
```http
GET  /pnl/summary              - P&L summary
GET  /pnl/daily                - Daily P&L report
GET  /pnl/history              - Historical P&L
```

#### Telegram
```http
POST /telegram/webhook         - Telegram bot webhook
POST /telegram/callback        - Interactive button callbacks
```

---

## 🤖 ExecutionBot Architecture (Unified Trade Execution)

**AlgoGPT v9.1** implements **ExecutionBot** — a centralized trade execution wrapper that consolidates all trade execution logic from multiple entry points into a single, unified interface.

### 🎯 Design Principles

**Problem**: Previously, trade execution logic was duplicated across 5+ entry points (API, Telegram, Ops Approval, Auto Scanner, Autopilot), making maintenance difficult and error-prone.

**Solution**: ExecutionBot wraps `trade_executor.py` and provides a single, consistent interface for all trade entry points:

```python
# All entry points now use ExecutionBot:
from utils.execution_bot import ExecutionBot

bot = ExecutionBot(logger=logger)
result = await bot.open_position(ticket_exec, source="api")
```

### 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Entry Points                         │
├─────────────────────────────────────────────────────────┤
│  /trade/execute  │  /telegram/webhook  │  /ops/approve  │
│  /auto/trade     │  /autopilot         │  callbacks     │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
      ┌────────────────────┐
      │  ExecutionBot      │  ← Unified wrapper
      │  utils/           │
      │  execution_bot.py  │
      └────────┬───────────┘
               │
               ├─→ _select_flow()        (MARKET/HYBRID)
               ├─→ _needs_approval()     (Approval gating)
               └─→ _execute_flow()       (Delegate to trade_executor)
               
               ▼
      ┌────────────────────┐
      │  trade_executor.py │  ← Core execution logic
      └────────────────────┘
```

### 🔄 Unified Flow

```python
# ExecutionBot.open_position() flow:
1. Source-aware approval gating (_needs_approval)
   - Already approved sources bypass approval
   - New requests check approval flags
   
2. Flow selection (_select_flow)
   - MARKET: Only budget_usd provided
   - HYBRID: TP/SL configuration provided
   
3. Execution delegation (_execute_flow)
   - Calls trade_executor functions
   - Handles -4061 errors (fallback to MARKET)
   - Returns unified response format
   
4. Centralized logging
   - "[ExecutionBot] open_position source=X flow=Y"
   - Consistent across all entry points
```

### 📋 Source-Aware Approval Gating

ExecutionBot intelligently bypasses approval for already-approved or automated sources:

```python
# Sources that execute immediately (bypass approval):
- "ops_approval", "ops_approval_get", "ops_approval_fallback"
  → Already approved via Telegram callbacks
  
- "telegram", "telegram_callback"
  → User-initiated, execute immediately
  
- "auto_trade", "autopilot"
  → Internal automation, execute immediately

# Sources that may need approval:
- "api"
  → Checks require_approval flag
```

### 🎯 Supported Flows

#### 🔸 MARKET Flow
- **When**: Only `budget_usd` provided
- **Execution**: Direct market order with ATR-based SL/TP
- **File**: `utils/trade_executor.py::execute_trade_market_only()`

#### 🔸 HYBRID Flow
- **When**: Custom TP/SL configuration provided
- **Execution**: LIMIT entry + STOP_MARKET SL + TAKE_PROFIT_MARKET TP
- **File**: `utils/trade_executor.py::execute_trade_hybrid()`
- **Fallback**: On -4061 error, falls back to MARKET flow

### 🔌 Entry Points Using ExecutionBot

| Entry Point | File | Source | Flow |
|-------------|------|--------|------|
| API Execute | `routes/trade.py` | `"api"` | MARKET/HYBRID |
| API Approve | `routes/trade.py` | `"approval"` | MARKET/HYBRID |
| Telegram | `routes/telegram_bot.py` | `"telegram"` | MARKET/HYBRID |
| Ops Approval | `routes/ops_approve.py` | `"ops_approval_get"` | HYBRID |
| Ops Fallback | `routes/ops_approve.py` | `"ops_approval_get_fallback"` | MARKET |
| Auto Trade | `routes/auto_trade.py` | `"auto_trade"` | MARKET/HYBRID |
| Autopilot | `routes/system_autopilot.py` | `"autopilot"` | MARKET/HYBRID |

### ✅ Benefits

- **Single Source of Truth**: All execution logic centralized
- **Consistent Logging**: Unified logging format across all entry points
- **Backward Compatible**: External API formats preserved
- **Source-Aware**: Intelligent approval gating per source
- **Fallback Handling**: Automatic HYBRID→MARKET fallback on errors
- **Easy Testing**: Single component to test instead of 5+
- **Future-Proof**: Easy to add new entry points or flows

### 📝 Example Usage

```python
from utils.execution_bot import ExecutionBot

bot = ExecutionBot(logger=logger)

ticket_exec = {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "position_side": "LONG",
    "budget_usd": 100.0,
    "leverage": 5,
    "dry_run": False,
}

result = await bot.open_position(ticket_exec, source="api")

if result["status"] == "opened":
    print(f"Position opened: {result['position_id']}")
elif result["status"] == "pending_approval":
    print(f"Awaiting approval: {result['telegram_msg_id']}")
else:
    print(f"Failed: {result['reason']}")
```

---

## 🔐 Security (HMAC Signature)

AlgoGPT uses **HMAC-SHA256 signatures** for all critical API calls to ensure authenticity and prevent replay attacks.

### 🔑 Signature Flow

```python
# 1. Generate timestamp + nonce
timestamp = str(int(time.time()))
nonce = secrets.token_hex(16)

# 2. Hash request body
body_hash = hashlib.sha256(body_bytes).hexdigest()

# 3. Build signature message
message = f"{timestamp}.{nonce}.{body_hash}"

# 4. Generate HMAC signature
secret = os.getenv("WEBHOOK_HMAC_SECRET")  # or OPS_SIGN_SECRET
signature = hmac.new(
    secret.encode(),
    message.encode(),
    hashlib.sha256
).hexdigest()

# 5. Send headers
headers = {
    "X-Timestamp": timestamp,
    "X-Nonce": nonce,
    "X-Signature": signature,
    "Digest": base64.b64encode(hashlib.sha256(body_bytes).digest())
}
```

### 🛡️ Anti-Replay Protection

- **Timestamp validation**: Requests older than 300 seconds are rejected
- **Nonce tracking**: Each nonce can only be used once
- **Constant-time comparison**: Prevents timing attacks

### 🔒 Supported Secrets (Priority Order)

1. `ALERTS_INGEST_HMAC_SECRET`
2. `WEBHOOK_HMAC_SECRET`
3. `ALERTS_HMAC_SECRET`
4. `OPS_SIGN_SECRET`
5. `ALERTS_WEBHOOK_SECRET`
6. `SECRET` (fallback)

**Hex Keys**: Set `<SECRET>_KEY_IS_HEX=1` if secret is hex-encoded.

---

## 📁 Project Structure

```
AlgoGPT/
├── main.py                    # FastAPI server
├── gunicorn_conf.py          # Gunicorn config
├── requirements.txt          # Python dependencies
├── replit.md                 # Project summary
├── README.md                 # This file
│
├── workers/                  # Background workers (8)
│   ├── auto_health_monitor.py    # Health monitoring
│   ├── gpt_auto_suggest.py       # Market scanner
│   ├── fills_watcher.py          # Order fills tracker
│   ├── position_monitor.py       # Position tracking + order cleanup
│   ├── daily_meeting.py          # Daily reports
│   ├── gpt5_orchestrator.py      # GPT-5 orchestrator
│   ├── sentinel_security.py      # Security monitoring
│   └── n8n_bridge.py             # N8N integration
│
├── routes/                   # FastAPI routes
│   ├── alerts.py             # Trade alert ingestion
│   ├── trade.py              # Trade execution
│   ├── grid.py               # GRID trading
│   ├── position_ops.py       # Position management
│   ├── telegram_webhook.py   # Telegram webhooks
│   └── dashboard.py          # UI dashboard
│
├── utils/                    # Core utilities
│   ├── ai_decision_maker.py       # 5 AI brains + consensus engine
│   ├── ai_post_trade_review.py   # Post-trade AI reviews
│   ├── ai_trade_scorer.py        # Multi-AI scoring
│   ├── anthropic_client.py       # Claude client
│   ├── gemini_client.py          # Gemini client
│   ├── xai_client.py             # Grok client
│   ├── strategy_orchestrator.py  # 7 strategies orchestrator
│   ├── mean_reversion_strategy.py
│   ├── regime_detector_v2.py     # Market regime detection
│   ├── market_intelligence.py    # Multi-TF analysis
│   ├── indicators.py             # 12 technical indicators
│   ├── indicators_ext.py         # Extended indicators (VWAP, OBV)
│   ├── indicators_smc.py         # Smart Money Concepts
│   ├── indicators_qqe.py         # QQE indicator
│   ├── binance_client.py         # Binance API wrapper
│   ├── security.py               # HMAC signature verification
│   ├── auto_executor.py          # Trade execution engine
│   ├── trade_manager.py          # Position management
│   └── portfolio_intelligence.py # Portfolio analysis
│
├── data/                     # Data storage
│   ├── ai_reviews/           # AI trade reviews
│   ├── backtest/             # Backtest results
│   └── cache/                # Cached data
│
└── monitoring/               # Monitoring & metrics
    └── grafana/              # Grafana dashboards
```

---

## 🚀 Installation & Setup

### Prerequisites

- Python 3.11+
- PostgreSQL (Neon recommended)
- Binance Futures Account
- API Keys: OpenAI, Anthropic, Google (Gemini), DeepSeek, XAI (Grok)

### 1. Clone Repository

```bash
git clone <repo_url>
cd AlgoGPT
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create `.env` file:

```bash
# Binance API
BINANCE_API_KEY=<your_binance_api_key>
BINANCE_API_SECRET=<your_binance_api_secret>

# Database
DATABASE_URL=postgresql://user:pass@host/db

# AI API Keys
OPENAI_API_KEY=<your_openai_key>
ANTHROPIC_API_KEY=<your_anthropic_key>
GEMINI_API_KEY=<your_gemini_key>
DEEPSEEK_API_KEY=<your_deepseek_key>
XAI_API_KEY=<your_xai_key>

# Telegram
TELEGRAM_BOT_TOKEN=<your_bot_token>
TELEGRAM_CHAT_ID=<your_chat_id>

# Security
WEBHOOK_HMAC_SECRET=<random_32_byte_hex>
OPS_SIGN_SECRET=<random_32_byte_hex>

# Trading Config
EXECUTE_TRADES=1
AUTO_RUN=1
ENABLE_MULTI_AI_CONSENSUS=1
```

### 4. Run Server

```bash
# Development
python main.py

# Production
gunicorn -c gunicorn_conf.py main:app
```

### 5. Start Workers

```bash
# Terminal 1: Auto Scanner
python workers/gpt_auto_suggest.py

# Terminal 2: Health Monitor
python workers/auto_health_monitor.py

# Terminal 3: Position Monitor
python workers/position_monitor.py

# Terminal 4: Fills Watcher
python workers/fills_watcher.py
```

---

## 📊 Performance Metrics

### Target Metrics (v9.0)
- **Daily Trades**: 4-10 high-quality trades
- **Win Rate**: ≥47%
- **Risk/Reward**: ≥1.3:1
- **Max Drawdown**: <10%
- **Uptime**: 99.9%

### AI Consensus Performance
- **Avg Consensus Time**: ~3-5 seconds
- **AI Agreement Rate**: ~60-80%
- **Quality Filter**: Avg score ≥5.8/10 (regime-based)

---

## 🗺️ Roadmap

### ✅ Completed (v9.0)
- [x] 5-brain AI consensus engine
- [x] Regime-based dynamic parameters
- [x] 7 trading strategies
- [x] Auto order cleanup on position close
- [x] HMAC signature security
- [x] 534 markets scanning

### 🚧 In Progress
- [ ] Machine learning trade outcome prediction
- [ ] Advanced portfolio optimization
- [ ] Multi-exchange support (Bybit, OKX)

### 📅 Future Plans
- [ ] Options trading support
- [ ] Copy trading API
- [ ] Mobile app (iOS/Android)

---

## 📝 Auto-Update Mechanism

This README.md is **automatically updated** on every code change using:

1. **Pre-commit hook** (`.git/hooks/pre-commit`)
2. **GitHub Action** (`.github/workflows/update-readme.yml`)

**Auto-detected metrics:**
- Number of AI brains
- Number of workers
- Number of strategies
- Number of indicators
- Version number
- Last update timestamp

---

## 📄 License

This project is **private and proprietary**. All rights reserved.

---

## 📞 Contact & Support

For questions or support, contact the development team.

---

<div align="center">

**Made with ❤️ by AlgoGPT Team**

**Last Updated**: 2025-11-12 | **Version**: 9.1.0

</div>
