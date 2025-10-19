# PR: Approvals flow hardening

This PR hardens the approval flow end-to-end.

## Highlights
- Security: fail-closed shims for anti-replay/idempotency; no unsigned approve/reject links.
- UX: signed GET now shows a confirm page; POST performs the action (prevents link-scanner triggers).
- Reliability: atomic idempotency guard for approve/reject (Redis SETNX, in-memory fallback).
- Lifecycle: clean shutdown of httpx AsyncClient and Redis.
- Messaging: concise Telegram error instead of dumping full execution payload.

## New/changed env
- HMAC_SECRET (required for signed approve/reject links)
- ALLOW_MISSING_ANTI_REPLAY=0 (default)
- ALLOW_MISSING_IDEMPOTENCY=0 (default)

## Test plan
- Without HMAC_SECRET => only preview links are emitted.
- With HMAC_SECRET => GET /ops/approve/signed shows confirm; POST performs.
- Double-click approve/reject => second attempt is skipped with a duplicate notice.
- Shutdown => no unclosed client warnings.
