# N8N Integration Workflows

Complete guide for integrating N8N workflows with AlgoGPT trading platform.

## Table of Contents

1. [Overview](#overview)
2. [Security Setup](#security-setup)
3. [Webhook Endpoints](#webhook-endpoints)
4. [Example Workflows](#example-workflows)
   - [News Ingestion](#1-news-ingestion-workflow)
   - [Trade Approval Escalation](#2-trade-approval-escalation-workflow)
   - [Incident Paging](#3-incident-paging-workflow)
5. [Testing & Debugging](#testing--debugging)
6. [Best Practices](#best-practices)

---

## Overview

AlgoGPT integrates with N8N (n8n.io) for workflow automation. This enables:

- **External data ingestion** (news, market data, social sentiment)
- **Human-in-the-loop approvals** (trade escalation, risk overrides)
- **Incident management** (alerting, paging, notifications)
- **System automation** (scheduled tasks, data pipelines)

### Architecture

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│   N8N       │  HTTPS  │  N8N Bridge  │  API    │  AlgoGPT    │
│  Workflows  ├────────>│  (Worker)    ├────────>│  Core       │
└─────────────┘         └──────────────┘         └─────────────┘
                             │
                             │ Fallback Queue
                             ├────> Redis/SQLite
                             │
                             │ Heartbeat
                             └────> Monitoring
```

---

## Security Setup

### 1. Generate HMAC Secret

Generate a strong secret for webhook signature validation:

```bash
# Linux/Mac
openssl rand -hex 32

# Output example:
# 8f4a9c2e7b1d3f6e5a8c9b2d4f7e1a3c6b9d2f5e8a1c4b7e0d3f6a9c2e5b8d1
```

### 2. Configure Environment Variables

Add to your `.env` file:

```bash
# N8N Integration
N8N_WEBHOOK_SECRET=8f4a9c2e7b1d3f6e5a8c9b2d4f7e1a3c6b9d2f5e8a1c4b7e0d3f6a9c2e5b8d1
N8N_HEARTBEAT_URL=https://your-n8n-instance.com/webhook/algogpt-heartbeat
N8N_FALLBACK_ENABLED=1  # Enable queue for failed webhooks
```

### 3. Add Workflow to AlgoGPT

Add to your workflow configuration:

```yaml
workflows:
  - name: "N8N Bridge"
    command: "cd /home/runner/$REPL_SLUG && PYTHONPATH=/home/runner/$REPL_SLUG python workers/n8n_bridge.py"
    output_type: "console"
```

---

## Webhook Endpoints

### Incoming Webhooks (N8N → AlgoGPT)

**Endpoint:** `POST /webhooks/n8n`

**Headers:**
```
Content-Type: application/json
X-N8N-Signature: <hmac_sha256_signature>
X-N8N-Timestamp: <unix_timestamp>
```

**Signature Calculation (Python):**
```python
import hmac
import hashlib
import time

payload = b'{"type": "news_ingestion", "title": "BTC breaks $100k"}'
secret = b'your_webhook_secret'
timestamp = int(time.time())

# Calculate signature
signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()

# Send webhook
headers = {
    "X-N8N-Signature": signature,
    "X-N8N-Timestamp": str(timestamp)
}
```

### Outgoing Webhooks (AlgoGPT → N8N)

AlgoGPT can send webhooks to N8N workflows:

```python
from workers.n8n_bridge import N8NBridge

bridge = N8NBridge()
await bridge.send_webhook_to_n8n(
    url="https://your-n8n-instance.com/webhook/trade-alert",
    data={
        "symbol": "BTCUSDT",
        "action": "LONG",
        "price": 110000.00,
        "confidence": 85.5
    }
)
```

---

## Example Workflows

### 1. News Ingestion Workflow

**Use Case:** Automatically fetch news from CryptoCompare, filter by relevance, and send to AlgoGPT for sentiment analysis.

#### N8N Workflow Setup

1. **Trigger Node**: Schedule Trigger (every 5 minutes)
2. **HTTP Request Node**: Fetch news from CryptoCompare
   ```
   URL: https://min-api.cryptocompare.com/data/v2/news/?lang=EN
   Method: GET
   ```
3. **Filter Node**: Keep only high-impact news
   ```javascript
   // Filter by categories
   {{ $json.categories.includes('BTC') || $json.categories.includes('ETH') }}
   ```
4. **Function Node**: Format payload for AlgoGPT
   ```javascript
   return {
     type: "news_ingestion",
     title: $json.title,
     body: $json.body,
     source: $json.source,
     sentiment: $json.sentiment || "neutral",
     symbols: $json.categories,
     timestamp: Date.now() / 1000
   };
   ```
5. **HTTP Request Node**: Send to AlgoGPT
   ```
   URL: https://your-algogpt.repl.co/webhooks/n8n
   Method: POST
   Headers:
     - X-N8N-Signature: {{ $node["Generate Signature"].json.signature }}
     - X-N8N-Timestamp: {{ $node["Generate Signature"].json.timestamp }}
   Body: {{ $json }}
   ```
6. **Function Node (Generate Signature)**:
   ```javascript
   const crypto = require('crypto');
   const secret = 'your_webhook_secret';
   const payload = JSON.stringify($json);
   const timestamp = Math.floor(Date.now() / 1000);
   
   const signature = crypto
     .createHmac('sha256', secret)
     .update(payload)
     .digest('hex');
   
   return {
     signature,
     timestamp
   };
   ```

**Expected Result:** News articles automatically ingested, analyzed for sentiment, and used to adjust trading bias.

---

### 2. Trade Approval Escalation Workflow

**Use Case:** When AlgoGPT proposes a high-risk trade (>$1000 or leverage >10x), escalate to human approval via Telegram/Slack.

#### N8N Workflow Setup

1. **Webhook Trigger Node**: Listen for trade proposals from AlgoGPT
   ```
   Webhook URL: /webhook/trade-approval-request
   Method: POST
   ```
2. **IF Node**: Check if trade needs approval
   ```javascript
   // High-risk criteria
   {{ $json.notional_usd > 1000 || $json.leverage > 10 }}
   ```
3. **Telegram Node** (or Slack): Send approval request
   ```
   Message:
   🚨 High-Risk Trade Approval Needed
   
   Symbol: {{ $json.symbol }}
   Side: {{ $json.side }}
   Size: ${{ $json.notional_usd }}
   Leverage: {{ $json.leverage }}x
   
   Quality Score: {{ $json.quality_score }}/10
   AI Confidence: {{ $json.ai_confidence }}%
   
   ✅ Approve: [link]
   ❌ Reject: [link]
   ```
4. **Wait Node**: Wait for human response (up to 5 minutes)
5. **HTTP Request Node**: Send approval/rejection back to AlgoGPT
   ```
   URL: https://your-algogpt.repl.co/webhooks/n8n
   Method: POST
   Body:
   {
     "type": "trade_approval",
     "trade_id": "{{ $json.trade_id }}",
     "action": "{{ $json.action }}",  // "APPROVE" or "REJECT"
     "approved_by": "{{ $json.approver }}"
   }
   ```

**Expected Result:** High-risk trades paused until human approves/rejects via Telegram/Slack.

---

### 3. Incident Paging Workflow

**Use Case:** When critical system issues occur (API outage, position liquidation, unusual losses), page on-call engineer.

#### N8N Workflow Setup

1. **Webhook Trigger Node**: Listen for incidents from AlgoGPT
   ```
   Webhook URL: /webhook/incident
   Method: POST
   ```
2. **Switch Node**: Route by severity
   ```
   Cases:
   - critical: severity === "critical"
   - high: severity === "high"
   - medium: severity === "medium"
   ```
3. **Critical Path**:
   - **PagerDuty Node**: Create incident
     ```
     Routing Key: your_pagerduty_routing_key
     Summary: {{ $json.message }}
     Severity: critical
     Custom Details: {{ $json }}
     ```
   - **SMS Node**: Send immediate SMS alert
   - **Telegram Node**: Send to emergency channel

4. **High Path**:
   - **Slack Node**: Post in #alerts channel
   - **Email Node**: Email on-call engineer

5. **Medium Path**:
   - **Slack Node**: Post in #monitoring channel

**Expected Result:** Critical incidents page on-call team immediately, high/medium incidents logged in appropriate channels.

---

## Testing & Debugging

### 1. Test Webhook Locally

Use `curl` to test webhook endpoint:

```bash
# Generate signature
SECRET="your_webhook_secret"
PAYLOAD='{"type":"news_ingestion","title":"Test News"}'
TIMESTAMP=$(date +%s)

SIGNATURE=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

# Send webhook
curl -X POST https://your-algogpt.repl.co/webhooks/n8n \
  -H "Content-Type: application/json" \
  -H "X-N8N-Signature: $SIGNATURE" \
  -H "X-N8N-Timestamp: $TIMESTAMP" \
  -d "$PAYLOAD"
```

### 2. Check Bridge Logs

Monitor N8N Bridge worker logs:

```bash
# View logs in real-time
tail -f /tmp/logs/n8n_bridge_*.log

# Check for errors
grep -i error /tmp/logs/n8n_bridge_*.log
```

### 3. Verify Heartbeat

Check bridge health status:

```bash
curl https://your-algogpt.repl.co/health/n8n-bridge
```

Expected response:
```json
{
  "status": "healthy",
  "uptime_seconds": 3600,
  "webhooks_received": 150,
  "errors": 2,
  "error_rate": 0.013,
  "last_webhook": 1699000000,
  "timestamp": "2024-11-02T22:00:00Z"
}
```

---

## Best Practices

### 1. Security

- ✅ **Always use HMAC signatures** for webhook validation
- ✅ **Rotate secrets quarterly** or after any suspected compromise
- ✅ **Use HTTPS only** for all webhook endpoints
- ✅ **Implement rate limiting** to prevent abuse (max 100 webhooks/minute)
- ✅ **Log all webhook attempts** for audit trail

### 2. Reliability

- ✅ **Enable fallback queue** to retry failed deliveries
- ✅ **Set timeout limits** (10s for webhooks, 60s for background tasks)
- ✅ **Monitor heartbeat** to detect bridge downtime
- ✅ **Implement circuit breakers** for external API calls

### 3. Performance

- ✅ **Process webhooks async** to avoid blocking
- ✅ **Batch similar operations** (e.g., multiple news items)
- ✅ **Cache frequently accessed data** (e.g., symbol mappings)
- ✅ **Use compression** for large payloads

### 4. Monitoring

- ✅ **Track webhook latency** (p50, p95, p99)
- ✅ **Alert on high error rates** (>5%)
- ✅ **Monitor queue depth** (alert if >100 items)
- ✅ **Log all approval decisions** for compliance

---

## Troubleshooting

### Issue: "Invalid signature" error

**Cause:** HMAC signature mismatch

**Solution:**
1. Verify `N8N_WEBHOOK_SECRET` matches on both sides
2. Check payload is exactly the same (no whitespace changes)
3. Ensure timestamp is within 5 minutes

### Issue: Webhooks not being received

**Cause:** Network/firewall issues

**Solution:**
1. Verify N8N can reach AlgoGPT endpoint
2. Check firewall rules allow incoming HTTPS
3. Test with `curl` from N8N server

### Issue: High queue depth

**Cause:** N8N endpoint down or slow

**Solution:**
1. Check N8N workflow is running
2. Verify N8N endpoint URL is correct
3. Increase timeout if N8N is slow

---

## Support

For issues or questions:
- **Logs**: Check `/tmp/logs/n8n_bridge_*.log`
- **Health**: `GET /health/n8n-bridge`
- **Documentation**: This file

---

**Last Updated:** November 2, 2025  
**Version:** 1.0.0  
**Author:** AlgoGPT Team
