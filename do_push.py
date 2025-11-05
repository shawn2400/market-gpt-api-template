#!/usr/bin/env python3
"""Quick script to commit and push changes to GitHub"""
import os
import subprocess
import sys

def run_cmd(cmd, check=True):
    """Run command and return result"""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if check and result.returncode != 0:
        raise Exception(f"Command failed: {' '.join(cmd)}")
    return result

def main():
    os.chdir('/home/runner/workspace')
    
    # Remove lock file if exists
    lock_file = '.git/index.lock'
    if os.path.exists(lock_file):
        print(f"Removing stale lock file: {lock_file}")
        os.remove(lock_file)
    
    # Add files
    print("\n1. Adding files...")
    run_cmd(['git', 'add', 'Procfile', 'workers/replit_agent_bridge.py', 'replit.md'])
    
    # Commit
    print("\n2. Committing...")
    result = run_cmd(['git', 'commit', '-m', 
                     'Make system fully independent from Replit - add 7 workers to Procfile'], 
                     check=False)
    
    if result.returncode != 0 and 'nothing to commit' in result.stdout:
        print("Nothing to commit - files already committed")
    elif result.returncode != 0:
        raise Exception("Commit failed")
    
    # Push
    print("\n3. Pushing to GitHub...")
    run_cmd(['git', 'push', 'origin', 'main'])
    
    print("\n✅ Successfully pushed to GitHub!")
    print("🚀 Render will auto-deploy in 2-3 minutes")

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
