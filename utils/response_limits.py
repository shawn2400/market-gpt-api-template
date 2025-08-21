from __future__ import annotations
import io, json
from starlette.types import ASGIApp, Scope, Receive, Send

class ResponseSizeLimiter:
    def __init__(self, app: ASGIApp, max_bytes: int = 1_048_576):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        buffer = io.BytesIO()
        started = {"done": False}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                return
            if message["type"] == "http.response.body":
                chunk = message.get("body", b"") or b""
                buffer.write(chunk)
                if message.get("more_body", False):
                    if buffer.tell() > self.max_bytes:
                        await _send_413(send, self.max_bytes)
                        started["done"] = True
                    return
                if buffer.tell() > self.max_bytes:
                    await _send_413(send, self.max_bytes)
                    started["done"] = True
                    return
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": buffer.getvalue()})
                started["done"] = True
                return
            await send(message)

        await self.app(scope, receive, send_wrapper)

async def _send_413(send: Send, max_bytes: int):
    data = json.dumps({"detail": "Response too large", "max_bytes": max_bytes}).encode()
    headers = [(b"content-type", b"application/json")]
    await send({"type": "http.response.start", "status": 413, "headers": headers})
    await send({"type": "http.response.body", "body": data})




