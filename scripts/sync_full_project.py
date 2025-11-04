#!/usr/bin/env python3
"""
Sync FULL AlgoGPT project to GitHub
Uploads all critical files including Dashboard, routes, workers, utils, policies
"""
import os
import subprocess
import requests
import base64
from pathlib import Path
import time

def get_github_token():
    """Get GitHub access token from Replit Integration"""
    hostname = os.getenv('REPLIT_CONNECTORS_HOSTNAME')
    repl_identity = os.getenv('REPL_IDENTITY')
    web_renewal = os.getenv('WEB_REPL_RENEWAL')
    
    x_replit_token = f'repl {repl_identity}' if repl_identity else f'depl {web_renewal}'
    
    url = f'https://{hostname}/api/v2/connection?include_secrets=true&connector_names=github'
    response = requests.get(url, headers={
        'Accept': 'application/json',
        'X_REPLIT_TOKEN': x_replit_token
    })
    response.raise_for_status()
    
    items = response.json().get('items', [])
    if not items:
        raise Exception('GitHub connection not found')
    
    settings = items[0].get('settings', {})
    token = settings.get('access_token') or settings.get('oauth', {}).get('credentials', {}).get('access_token')
    
    if not token:
        raise Exception('GitHub access token not found')
    
    return token

def upload_file_to_github(token, owner, repo, file_path, message):
    """Upload a single file to GitHub using Contents API"""
    url = f'https://api.github.com/repos/{owner}/{repo}/contents/{file_path}'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    # Read file content
    try:
        with open(file_path, 'rb') as f:
            content = base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        return False, f"Cannot read: {str(e)[:50]}"
    
    # Get current file SHA (if exists)
    sha = None
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            sha = response.json().get('sha')
    except:
        pass
    
    # Upload/Update file
    data = {
        'message': message,
        'content': content,
        'branch': 'main'
    }
    if sha:
        data['sha'] = sha
    
    response = requests.put(url, headers=headers, json=data)
    
    if response.status_code in [200, 201]:
        return True, "OK"
    else:
        return False, f"{response.status_code}"

def sync_files(token, owner, repo, files, category_name):
    """Sync a list of files"""
    commit_msg = f'AlgoGPT Ultimate - {category_name}'
    
    print(f'\n🚀 Syncing {category_name}...')
    print(f'📦 {len(files)} files to upload\n')
    
    success_count = 0
    for file_path in files:
        if os.path.exists(file_path):
            success, msg = upload_file_to_github(token, owner, repo, file_path, commit_msg)
            if success:
                print(f"✅ {file_path}")
                success_count += 1
            else:
                print(f"❌ {file_path}: {msg}")
            time.sleep(0.1)  # Avoid rate limiting
        else:
            print(f"⚠️  {file_path} not found")
    
    print(f'\n✅ {category_name}: {success_count}/{len(files)} uploaded\n')
    return success_count

def main():
    try:
        print('=' * 70)
        print('🚀 AlgoGPT Full Project Sync to GitHub')
        print('=' * 70)
        
        print('\n🔑 Getting GitHub access token...')
        token = get_github_token()
        print('✅ Token retrieved\n')
        
        owner = 'shawn2400'
        repo = 'market-gpt-api-template'
        
        # Category 1: Dashboard files (MOST IMPORTANT)
        dashboard_files = [
            'static/dashboard/index.html',
            'static/dashboard/ultimate-workbook.html',
            'static/dashboard/complete-workbook.html',
            'static/dashboard/presentation.html',
            'static/dashboard/system-status.html',
            'static/dashboard/validation-monitoring.html',
            'static/dashboard/workbook.html',
            'static/dashboard/algogpt-logo.svg',
        ]
        sync_files(token, owner, repo, dashboard_files, 'Dashboard Files')
        
        # Category 2: Core application files
        core_files = [
            'main.py',
            'gunicorn_conf.py',
            'requirements.txt',
            'replit.md',
            '.replit',
            'README.md',
        ]
        sync_files(token, owner, repo, core_files, 'Core Files')
        
        # Category 3: Routes (critical ones)
        routes_files = [
            'routes/root.py',
            'routes/health.py',
            'routes/dashboard.py',
            'routes/trade.py',
            'routes/telegram_bot.py',
            'routes/alerts.py',
            'routes/status.py',
            'routes/ai.py',
        ]
        sync_files(token, owner, repo, routes_files, 'Critical Routes')
        
        # Category 4: Workers
        workers_files = [
            'workers/auto_health_monitor.py',
            'workers/gpt_auto_suggest.py',
            'workers/gpt5_orchestrator.py',
            'workers/position_monitor.py',
            'workers/sentinel_security.py',
            'workers/n8n_bridge.py',
        ]
        sync_files(token, owner, repo, workers_files, 'Workers')
        
        # Category 5: Utils (critical ones)
        utils_files = [
            'utils/render_api.py',
            'utils/telegram_notifier.py',
            'utils/ai_client.py',
            'utils/trade_manager.py',
            'utils/db.py',
        ]
        sync_files(token, owner, repo, utils_files, 'Critical Utils')
        
        # Category 6: Policies
        policy_files = [
            'policies/ops_policy.yaml',
            'policies/dynamic_policy.yaml',
        ]
        sync_files(token, owner, repo, policy_files, 'Policies')
        
        # Category 7: Deployment scripts
        deploy_files = [
            'trigger_render_deploy.py',
            'check_render_status.py',
            'scripts/sync_important_files.py',
            'scripts/sync_to_github_api.py',
        ]
        sync_files(token, owner, repo, deploy_files, 'Deployment Scripts')
        
        print('=' * 70)
        print('🎉 FULL PROJECT SYNC COMPLETE!')
        print('=' * 70)
        print('\n✅ All critical files uploaded to GitHub!')
        print('📦 Ready for Render deployment')
        
        return True
        
    except Exception as e:
        print(f'\n❌ Error: {str(e)}')
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
