import httpx
import asyncio
import time

async def test_health_endpoint():
    async with httpx.AsyncClient() as client:
        tasks = [client.get("http://127.0.0.1:5000/monitors/health") for _ in range(100)]
        start = time.time()
        responses = await asyncio.gather(*tasks)
        duration = time.time() - start
        
        success = sum(1 for r in responses if r.status_code == 200)
        print(f"✅ {success}/100 requests succeeded in {duration:.2f}s")

asyncio.run(test_health_endpoint())
