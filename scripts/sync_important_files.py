#!/usr/bin/env python3
"""
Push the most important files to GitHub using GitHub API
Prioritizes critical files for deployment
"""
import os
import subprocess
import requests
import base64
from pathlib import Path

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
        print(f"❌ Could not read {file_path}: {str(e)}")
        return False
    
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
        print(f"✅ {file_path}")
        return True
    else:
        print(f"❌ {file_path}: {response.status_code}")
        return False

def sync_to_github():
    """Sync critical files to GitHub"""
    try:
        print('🔑 Getting GitHub access token...')
        token = get_github_token()
        print('✅ Token retrieved\n')
        
        owner = 'shawn2400'
        repo = 'market-gpt-api-template'
        commit_msg = 'AlgoGPT Ultimate Edition - Dashboard and core files'
        
        # Priority files - most important for deployment
        priority_files = [
            'main.py',
            'gunicorn_conf.py',
            'requirements.txt',
            'replit.md',
            'static/dashboard/index.html',
            'routes/__init__.py',
            'routes/monitors.py',
            'routes/validation.py',
            'utils/__init__.py',
            'utils/monitors/__init__.py',
            'utils/monitors/circuit_breaker.py',
            'utils/monitors/live_health.py',
            'utils/validation.py',
            'trigger_render_deploy.py',
            'check_render_status.py',
            'utils/render_api.py',
        ]
        
        print(f'🚀 Syncing priority files to GitHub\n')
        
        success_count = 0
        for file_path in priority_files:
            if os.path.exists(file_path):
                if upload_file_to_github(token, owner, repo, file_path, commit_msg):
                    success_count += 1
            else:
                print(f"⚠️ {file_path} not found")
        
        print(f'\n✅ Successfully synced {success_count}/{len(priority_files)} priority files to GitHub!')
        return True
        
    except Exception as e:
        print(f'❌ Error: {str(e)}')
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    sync_to_github()
