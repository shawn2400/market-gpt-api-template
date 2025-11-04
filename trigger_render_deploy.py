#!/usr/bin/env python3
"""
AlgoGPT - Trigger Render Deployment
Triggers deployment on algogpt-docker service via Render API
"""

import asyncio
import sys
from utils.render_api import RenderAPI

SERVICE_ID = "srv-d2346lfgi27c73fii3ag"  # algogpt-docker

async def main():
    try:
        print("🚀 AlgoGPT - Triggering Render Deployment...")
        print("=" * 50)
        
        # Initialize Render API
        render = RenderAPI()
        
        # Get current service info
        print(f"\n📋 Service: algogpt-docker")
        print(f"🆔 ID: {SERVICE_ID}")
        
        try:
            service_info = await render.get_service(SERVICE_ID)
            service_data = service_info.get("service", {})
            service_url = service_data.get("serviceDetails", {}).get("url", "N/A")
            print(f"🌐 URL: {service_url}")
        except Exception as e:
            print(f"⚠️  Could not fetch service info: {str(e)}")
            service_url = "https://algogpt-docker.onrender.com"
        
        # Trigger deployment
        print(f"\n⚡ Triggering deployment...")
        deploy_result = await render.trigger_deploy(SERVICE_ID)
        
        status = deploy_result.get("status", "unknown")
        message = deploy_result.get("message", "Deployment triggered")
        
        print(f"✅ {message}")
        print(f"📊 Status: {status}")
        
        print("\n" + "=" * 50)
        print("🎯 Deployment in progress!")
        print("\n⏱️  Expected time: 5-10 minutes")
        print("\n🌐 Your Dashboard will be ready at:")
        print(f"   {service_url}/static/dashboard/index.html")
        print("\n💡 Check status at:")
        print("   https://dashboard.render.com/web/srv-d2346lfgi27c73fii3ag")
        print("=" * 50)
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
