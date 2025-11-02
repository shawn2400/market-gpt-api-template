#!/usr/bin/env python3
import os
import subprocess
import requests
import json

def get_access_token():
    """Get GitHub access token from Replit GitHub Integration"""
    hostname = os.getenv('REPLIT_CONNECTORS_HOSTNAME')
    repl_identity = os.getenv('REPL_IDENTITY')
    web_renewal = os.getenv('WEB_REPL_RENEWAL')
    
    x_replit_token = None
    if repl_identity:
        x_replit_token = f'repl {repl_identity}'
    elif web_renewal:
        x_replit_token = f'depl {web_renewal}'
    
    if not x_replit_token:
        raise Exception('REPL_IDENTITY or WEB_REPL_RENEWAL not found')
    
    url = f'https://{hostname}/api/v2/connection?include_secrets=true&connector_names=github'
    headers = {
        'Accept': 'application/json',
        'X_REPLIT_TOKEN': x_replit_token
    }
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    data = response.json()
    items = data.get('items', [])
    
    if not items:
        raise Exception('GitHub connection not found')
    
    connection = items[0]
    settings = connection.get('settings', {})
    
    access_token = settings.get('access_token')
    if not access_token:
        oauth = settings.get('oauth', {})
        credentials = oauth.get('credentials', {})
        access_token = credentials.get('access_token')
    
    if not access_token:
        raise Exception('GitHub access token not found in connection')
    
    return access_token

def push_to_github():
    """Push all commits to GitHub using integration token"""
    try:
        print('🔑 Getting GitHub access token from Replit Integration...')
        token = get_access_token()
        print('✅ Token retrieved successfully')
        
        print('📝 Configuring git remote with authentication...')
        repo = 'github.com/shawn2400/market-gpt-api-template.git'
        remote_url = f'https://x-access-token:{token}@{repo}'
        
        subprocess.run(['git', 'remote', 'set-url', 'origin', remote_url], check=True)
        print('✅ Git remote configured')
        
        print('🚀 Pushing all commits to GitHub...')
        result = subprocess.run(
            ['git', 'push', 'origin', 'main'],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print('✅ Push completed successfully!')
            print(result.stdout)
        else:
            print('❌ Push failed:')
            print(result.stderr)
            return False
            
        return True
        
    except Exception as e:
        print(f'❌ Error: {str(e)}')
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = push_to_github()
    exit(0 if success else 1)
