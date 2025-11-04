#!/usr/bin/env python3
"""
AlgoGPT - Check Render Deployment Status
"""

import asyncio
import httpx
from datetime import datetime

SERVICE_ID = "srv-d2346lfgi27c73fii3ag"
SERVICE_URL = "https://algogpt-docker.onrender.com"
DASHBOARD_URL = f"{SERVICE_URL}/static/dashboard/index.html"

async def check_service_health():
    """Check if the service is responding"""
    print("🔍 Checking service health...")
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{SERVICE_URL}/health", follow_redirects=True)
            if response.status_code == 200:
                print(f"✅ Service is UP! (Status: {response.status_code})")
                return True
            else:
                print(f"⚠️  Service responded with status: {response.status_code}")
                return False
    except Exception as e:
        print(f"❌ Service is DOWN: {str(e)}")
        return False

async def check_dashboard():
    """Check if the dashboard is accessible"""
    print("\n🎨 Checking Dashboard...")
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(DASHBOARD_URL, follow_redirects=True)
            if response.status_code == 200:
                print(f"✅ Dashboard is accessible! (Status: {response.status_code})")
                print(f"🌐 URL: {DASHBOARD_URL}")
                return True
            else:
                print(f"⚠️  Dashboard responded with status: {response.status_code}")
                return False
    except Exception as e:
        print(f"❌ Dashboard not accessible yet: {str(e)}")
        return False

async def main():
    print("=" * 60)
    print("🚀 AlgoGPT - Render Deployment Status Check")
    print(f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    service_ok = await check_service_health()
    dashboard_ok = await check_dashboard()
    
    print("\n" + "=" * 60)
    if service_ok and dashboard_ok:
        print("🎉 DEPLOYMENT SUCCESSFUL!")
        print(f"\n🌐 Your AlgoGPT Dashboard is ready:")
        print(f"   {DASHBOARD_URL}")
    elif service_ok:
        print("⏳ Service is up but dashboard not ready yet...")
        print("   Please wait a few more minutes and try again.")
    else:
        print("⏳ Deployment still in progress...")
        print("   Expected time: 5-10 minutes from trigger")
        print(f"\n💡 Check status at:")
        print(f"   https://dashboard.render.com/web/{SERVICE_ID}")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
