#!/usr/bin/env python3
"""
AlgoGPT Ultimate Edition - Render Deployment Script
Automatically creates all services on Render.com
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.render_api import RenderAPI

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
GITHUB_REPO = os.getenv("GITHUB_REPO", "https://github.com/YOUR_USERNAME/algogpt-ultimate")
BRANCH = os.getenv("GITHUB_BRANCH", "main")
REGION = "singapore"  # Closest to crypto markets

# Environment variables to set
ENV_VARS = [
    {"key": "BINANCE_API_KEY", "value": os.getenv("BINANCE_API_KEY", "")},
    {"key": "BINANCE_API_SECRET", "value": os.getenv("BINANCE_API_SECRET", "")},
    {"key": "TELEGRAM_BOT_TOKEN", "value": os.getenv("TELEGRAM_BOT_TOKEN", "")},
    {"key": "TELEGRAM_CHAT_ID", "value": os.getenv("TELEGRAM_CHAT_ID", "")},
    {"key": "TELEGRAM_ADMIN_IDS", "value": os.getenv("TELEGRAM_ADMIN_IDS", "")},
    {"key": "OPENAI_API_KEY", "value": os.getenv("OPENAI_API_KEY", "")},
    {"key": "XAI_API_KEY", "value": os.getenv("XAI_API_KEY", "")},
    {"key": "AI_MESH_SECRET", "value": os.getenv("AI_MESH_SECRET", "")},
    {"key": "OPS_SIGN_SECRET", "value": os.getenv("OPS_SIGN_SECRET", "")},
    {"key": "N8N_WEBHOOK_SECRET", "value": os.getenv("N8N_WEBHOOK_SECRET", "")},
]


async def deploy_all():
    """Deploy all services to Render"""
    render = RenderAPI()
    
    print("\n" + "="*60)
    print("🚀 AlgoGPT Ultimate Edition - Render Deployment")
    print("="*60 + "\n")
    
    # Step 1: Create PostgreSQL Database
    print("📊 Step 1/8: Creating PostgreSQL Database...")
    try:
        db_result = await render.create_postgres_database(
            name="algogpt-db",
            database_name="algogpt",
            user="algogpt_user",
            plan="starter",  # $7/mo
            region=REGION
        )
        db_id = db_result["id"]
        db_connection_string = db_result.get("connectionString", "")
        print(f"   ✅ Database created: {db_id}")
        print(f"   📍 Connection: {db_connection_string[:50]}...")
        
        # Add DATABASE_URL to env vars
        ENV_VARS.append({"key": "DATABASE_URL", "value": db_connection_string})
    except Exception as e:
        logger.error(f"   ❌ Failed to create database: {e}")
        print("   ⚠️  Continuing with existing database (if any)...")
    
    await asyncio.sleep(2)
    
    # Step 2: Create Main Web Service (AlgoGPT Server)
    print("\n🌐 Step 2/8: Creating AlgoGPT Server (Web Service)...")
    try:
        server_start_cmd = """AUTO_RUN=1 EXECUTE_TRADES=1 TRADE_AUTO_SUGGEST=1 SUGGEST_FUTURES=1 \
ALLOW_MANAGE_OPEN_TRADES=1 PAUSE_AUTO_RUN=0 MANAGER_ENABLE=1 TRADE_MANAGER_ENABLE=1 \
TELEGRAM_SEND_ENABLE=1 APPROVAL_ENABLED=1 REQUIRE_TELEGRAM_APPROVAL=1 AUTO_OPEN_ON_APPROVE=1 \
SMART_MANAGE_ON_APPROVE=1 TRAIL_ENABLE=1 BE_GUARD_ENABLE=1 DEBUG_SIGN=1 \
ENABLE_MULTI_AI_CONSENSUS=1 ENABLE_OPENAI=1 ENABLE_DEEPSEEK=1 ENABLE_XAI=1 \
CONSENSUS_MIN_PROVIDERS=2 PORT=10000 gunicorn -c gunicorn_conf.py main:app"""
        
        web_result = await render.create_web_service(
            name="algogpt-server",
            repo_url=GITHUB_REPO,
            branch=BRANCH,
            build_command="pip install -r requirements.txt",
            start_command=server_start_cmd,
            env_vars=ENV_VARS,
            plan="standard",  # $25/mo for 2GB RAM
            region=REGION
        )
        web_id = web_result["service"]["id"]
        web_url = web_result["service"]["serviceDetails"]["url"]
        print(f"   ✅ Web Service created: {web_id}")
        print(f"   🌍 URL: {web_url}")
        
        # Update PUBLIC_HOST in env vars for workers
        ENV_VARS.append({"key": "PUBLIC_HOST", "value": web_url})
    except Exception as e:
        logger.error(f"   ❌ Failed to create web service: {e}")
        return False
    
    await asyncio.sleep(2)
    
    # Step 3-8: Create Background Workers
    workers = [
        {
            "name": "algogpt-health-monitor",
            "description": "Auto Health Monitor",
            "start_command": f"cd /opt/render/project/src && PYTHONPATH=/opt/render/project/src BASE_URL={web_url} HEALTH_CHECK_INTERVAL=30 AUTO_FIX_ENABLE=1 TELEGRAM_SEND_ENABLE=1 python workers/auto_health_monitor.py"
        },
        {
            "name": "algogpt-scanner",
            "description": "Auto Scanner (GPT Auto Suggest)",
            "start_command": f"cd /opt/render/project/src && PYTHONPATH=/opt/render/project/src TRADE_AUTO_SUGGEST=1 SUGGEST_FUTURES=1 SUGGEST_GRID=1 SUGGEST_INTERVAL_SEC=60 CONTEXT_URL={web_url} ALERT_INGEST_URL={web_url}/alerts/ingest WEBHOOK_HMAC_SECRET=demo_secret_change_in_production ENABLE_MULTI_AI_CONSENSUS=1 ENABLE_OPENAI=1 ENABLE_DEEPSEEK=1 ENABLE_XAI=1 python workers/gpt_auto_suggest.py"
        },
        {
            "name": "algogpt-gpt5-brain",
            "description": "GPT-5 Central Brain",
            "start_command": "cd /opt/render/project/src && PYTHONPATH=/opt/render/project/src python workers/gpt5_orchestrator.py"
        },
        {
            "name": "algogpt-n8n-bridge",
            "description": "N8N Bridge",
            "start_command": "cd /opt/render/project/src && PYTHONPATH=/opt/render/project/src python workers/n8n_bridge.py"
        },
        {
            "name": "algogpt-position-monitor",
            "description": "Position Monitor",
            "start_command": "cd /opt/render/project/src && PYTHONPATH=/opt/render/project/src ENABLE_POSITION_MONITOR=1 POSITION_REPORT_INTERVAL_SEC=1800 POSITION_ALERT_LEVEL=critical python workers/position_monitor.py"
        },
        {
            "name": "algogpt-sentinel",
            "description": "Sentinel Security",
            "start_command": "cd /opt/render/project/src && PYTHONPATH=/opt/render/project/src SENTINEL_ENABLED=1 SENTINEL_ALERT_LEVEL=critical python workers/sentinel_security.py"
        }
    ]
    
    for idx, worker in enumerate(workers, start=3):
        print(f"\n🔧 Step {idx}/8: Creating {worker['description']}...")
        try:
            worker_result = await render.create_background_worker(
                name=worker["name"],
                repo_url=GITHUB_REPO,
                branch=BRANCH,
                build_command="pip install -r requirements.txt",
                start_command=worker["start_command"],
                env_vars=ENV_VARS,
                plan="starter",  # $7/mo per worker
                region=REGION
            )
            worker_id = worker_result["service"]["id"]
            print(f"   ✅ Worker created: {worker_id}")
        except Exception as e:
            logger.error(f"   ❌ Failed to create worker: {e}")
            print(f"   ⚠️  Continuing...")
        
        await asyncio.sleep(2)
    
    # Summary
    print("\n" + "="*60)
    print("✅ DEPLOYMENT COMPLETE!")
    print("="*60)
    print(f"\n🌍 Your AlgoGPT is live at: {web_url}")
    print(f"📊 Dashboard: {web_url}/static/dashboard/index.html")
    print("\n📝 Services Created:")
    print("   1. algogpt-db (PostgreSQL)")
    print("   2. algogpt-server (Web Service)")
    print("   3. algogpt-health-monitor (Worker)")
    print("   4. algogpt-scanner (Worker)")
    print("   5. algogpt-gpt5-brain (Worker)")
    print("   6. algogpt-n8n-bridge (Worker)")
    print("   7. algogpt-position-monitor (Worker)")
    print("   8. algogpt-sentinel (Worker)")
    print("\n💰 Estimated Monthly Cost:")
    print("   - Database: $7/mo")
    print("   - Web Service: $25/mo (2GB RAM)")
    print("   - Workers (6x): $42/mo ($7 each)")
    print("   - TOTAL: ~$74/mo")
    print("\n⏳ Services will take 5-10 minutes to build and deploy.")
    print("📱 Check your Telegram for notifications!")
    print("="*60 + "\n")
    
    return True


async def list_existing_services():
    """List existing Render services"""
    render = RenderAPI()
    
    print("\n📋 Existing Render Services:")
    print("="*60)
    
    try:
        services = await render.list_services()
        
        if not services:
            print("   No services found.")
        else:
            for service in services:
                svc = service.get("service", {})
                name = svc.get("name", "N/A")
                svc_type = svc.get("type", "N/A")
                url = svc.get("serviceDetails", {}).get("url", "N/A")
                status = svc.get("state", "N/A")
                print(f"   • {name} ({svc_type}) - {status}")
                if url != "N/A":
                    print(f"     URL: {url}")
    except Exception as e:
        logger.error(f"Failed to list services: {e}")
    
    print("="*60 + "\n")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Deploy AlgoGPT to Render")
    parser.add_argument("--list", action="store_true", help="List existing services")
    parser.add_argument("--deploy", action="store_true", help="Deploy all services")
    
    args = parser.parse_args()
    
    if args.list:
        asyncio.run(list_existing_services())
    elif args.deploy:
        asyncio.run(deploy_all())
    else:
        parser.print_help()
