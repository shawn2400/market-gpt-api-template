#!/usr/bin/env python3
"""
Add RENDER_SERVICE_ID to GitHub Secrets automatically.
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
    SERVICE_ID = "srv-d4ddm1q4d50c73dmrkbg"  # algogpt-trading-vm
    REPO = "shawn2400/market-gpt-api-template"
    
    if not GITHUB_TOKEN:
        print("❌ GITHUB_TOKEN environment variable not set")
        sys.exit(1)
    
    print(f"🔐 Adding RENDER_SERVICE_ID to GitHub secrets for {REPO}...")
    print(f"📝 Service ID: {SERVICE_ID}")
    
    try:
        status = create_or_update_secret(REPO, GITHUB_TOKEN, "RENDER_SERVICE_ID", SERVICE_ID)
        if status in [201, 204]:
            print("✅ RENDER_SERVICE_ID secret created/updated successfully!")
            print("\n🎉 Auto-deployment is now configured!")
            print("📋 Next push to main will trigger automatic Render deployment")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
