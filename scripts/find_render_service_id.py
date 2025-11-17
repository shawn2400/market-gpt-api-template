#!/usr/bin/env python3
"""
Find Render service ID for algogpt-trading-vm using Render API.
"""

import os
import sys
import requests

def main():
    RENDER_API_KEY = os.environ.get("RENDER_API_KEY")
    
    if not RENDER_API_KEY:
        print("❌ RENDER_API_KEY environment variable not set")
        sys.exit(1)
    
    print("🔍 Finding Render service ID for algogpt-trading-vm...")
    
    headers = {
        "Authorization": f"Bearer {RENDER_API_KEY}",
        "Accept": "application/json"
    }
    
    try:
        # List all services
        response = requests.get("https://api.render.com/v1/services", headers=headers)
        response.raise_for_status()
        
        services = response.json()
        
        # Find algogpt-trading-vm
        for service in services:
            if service.get("service", {}).get("name") == "algogpt-trading-vm":
                service_id = service["service"]["id"]
                service_name = service["service"]["name"]
                region = service["service"].get("region", "N/A")
                
                print(f"\n✅ Found service!")
                print(f"   Name: {service_name}")
                print(f"   ID: {service_id}")
                print(f"   Region: {region}")
                print(f"\n📋 Next step: Add this to GitHub Secrets:")
                print(f"   Name: RENDER_SERVICE_ID")
                print(f"   Value: {service_id}")
                print(f"\n🔗 GitHub Secrets URL:")
                print(f"   https://github.com/shawn2400/market-gpt-api-template/settings/secrets/actions")
                
                return service_id
        
        print("❌ Service 'algogpt-trading-vm' not found")
        print("\n📋 Available services:")
        for service in services:
            name = service.get("service", {}).get("name", "Unknown")
            sid = service.get("service", {}).get("id", "Unknown")
            print(f"   - {name} ({sid})")
        
        sys.exit(1)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
