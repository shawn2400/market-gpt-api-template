#!/usr/bin/env python3
"""
Setup script to add RENDER_API_KEY to GitHub repository secrets.
This enables automatic deployment from GitHub to Render.
"""

import os
import sys
import requests
import base64
from nacl import encoding, public

def get_public_key(repo, token):
    """Get the repository's public key for encrypting secrets."""
    url = f"https://api.github.com/repos/{repo}/actions/secrets/public-key"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def encrypt_secret(public_key: str, secret_value: str) -> str:
    """Encrypt a secret using the repository's public key."""
    public_key_obj = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key_obj)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")

def create_or_update_secret(repo, token, secret_name, secret_value):
    """Create or update a GitHub Actions secret."""
    # Get public key
    key_data = get_public_key(repo, token)
    
    # Encrypt the secret
    encrypted_value = encrypt_secret(key_data["key"], secret_value)
    
    # Upload the secret
    url = f"https://api.github.com/repos/{repo}/actions/secrets/{secret_name}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    data = {
        "encrypted_value": encrypted_value,
        "key_id": key_data["key_id"]
    }
    
    response = requests.put(url, headers=headers, json=data)
    response.raise_for_status()
    return response.status_code

def main():
    # Configuration
    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
    RENDER_API_KEY = os.environ.get("RENDER_API_KEY")
    REPO = "shawn2400/market-gpt-api-template"
    
    if not GITHUB_TOKEN:
        print("❌ GITHUB_TOKEN environment variable not set")
        sys.exit(1)
    
    if not RENDER_API_KEY:
        print("❌ RENDER_API_KEY environment variable not set")
        sys.exit(1)
    
    print(f"🔐 Setting up GitHub secrets for {REPO}...")
    
    try:
        # Add RENDER_API_KEY secret
        print("📝 Adding RENDER_API_KEY secret...")
        status = create_or_update_secret(REPO, GITHUB_TOKEN, "RENDER_API_KEY", RENDER_API_KEY)
        if status in [201, 204]:
            print("✅ RENDER_API_KEY secret created/updated successfully")
        
        # Note about RENDER_SERVICE_ID
        print("\n⚠️  IMPORTANT: You need to add RENDER_SERVICE_ID manually:")
        print("1. Go to: https://dashboard.render.com/web/algogpt-trading-vm")
        print("2. Copy the Service ID from the URL (srv-xxxxx)")
        print("3. Add it to GitHub Secrets:")
        print(f"   https://github.com/{REPO}/settings/secrets/actions")
        print("   Name: RENDER_SERVICE_ID")
        print("   Value: srv-xxxxx (your service ID)")
        
        print("\n✅ Setup complete! Push to main branch will trigger auto-deployment.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
