# GitHub Sync Documentation

Complete guide for syncing AlgoGPT with GitHub repository.

## Table of Contents

1. [Overview](#overview)
2. [Initial Setup](#initial-setup)
3. [Sync Workflow](#sync-workflow)
4. [Branch Strategy](#branch-strategy)
5. [Automation](#automation)
6. [Troubleshooting](#troubleshooting)

---

## Overview

AlgoGPT uses Git for version control with GitHub as the remote repository. This enables:
- Code backup and disaster recovery
- Collaboration with team members
- Version history and rollback capability
- CI/CD integration

**Repository:** `https://github.com/your-org/algogpt`  
**Primary Branch:** `main`  
**Development Branch:** `develop`

---

## Initial Setup

### 1. Configure Git Identity

```bash
git config --global user.name "AlgoGPT Bot"
git config --global user.email "bot@algogpt.com"
```

### 2. Add GitHub Remote

```bash
# If not already added
git remote add origin https://github.com/your-org/algogpt.git

# Verify
git remote -v
```

### 3. Set Up GitHub Token (for HTTPS)

Create a Personal Access Token (PAT) on GitHub:
1. Go to GitHub Settings → Developer settings → Personal access tokens
2. Generate new token (classic)
3. Select scopes: `repo` (full control)
4. Copy the token

Store in environment:
```bash
export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"

# Or add to .env
echo "GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx" >> .env
```

Configure credential helper:
```bash
git config --global credential.helper store
echo "https://${GITHUB_TOKEN}@github.com" > ~/.git-credentials
```

---

## Sync Workflow

### Manual Sync (Recommended)

**Before making changes:**
```bash
# 1. Pull latest from GitHub
git pull origin main

# 2. Check status
git status

# 3. Make your changes...
```

**After making changes:**
```bash
# 1. Stage changes
git add .

# 2. Commit with descriptive message
git commit -m "feat: add multi-timeframe weighted analysis"

# 3. Push to GitHub
git push origin main
```

### Automated Sync Script

Create `scripts/sync_github.sh`:

```bash
#!/bin/bash
# Auto-sync with GitHub

set -e

echo "🔄 Syncing with GitHub..."

# Pull latest
echo "📥 Pulling latest from origin/main..."
git pull origin main --rebase

# Check if there are changes to commit
if [ -n "$(git status --porcelain)" ]; then
    echo "📝 Committing changes..."
    
    # Generate commit message
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S UTC')
    COMMIT_MSG="chore: auto-sync ${TIMESTAMP}"
    
    git add .
    git commit -m "$COMMIT_MSG"
    
    echo "📤 Pushing to origin/main..."
    git push origin main
    
    echo "✅ Sync complete!"
else
    echo "✅ Already up to date!"
fi
```

Make executable:
```bash
chmod +x scripts/sync_github.sh
```

Run:
```bash
./scripts/sync_github.sh
```

---

## Branch Strategy

### Main Branches

- **`main`**: Production-ready code
  - Protected branch
  - Requires pull request review
  - Auto-deploys to production

- **`develop`**: Development integration branch
  - Latest features in testing
  - Merges to `main` when stable

### Feature Branches

For new features:
```bash
# Create feature branch
git checkout -b feature/multi-tf-intelligence

# Make changes...
git add .
git commit -m "feat: implement weighted multi-TF analysis"

# Push to GitHub
git push origin feature/multi-tf-intelligence
```

Create Pull Request on GitHub:
1. Go to repository → Pull Requests
2. Click "New Pull Request"
3. Base: `develop`, Compare: `feature/multi-tf-intelligence`
4. Add description, request review
5. Merge when approved

### Hotfix Branches

For urgent production fixes:
```bash
# Create hotfix branch from main
git checkout main
git checkout -b hotfix/critical-bug-fix

# Make fix...
git commit -m "fix: resolve critical trading bug"

# Push and create PR to main
git push origin hotfix/critical-bug-fix
```

---

## Automation

### Option 1: Cron Job

Add to crontab:
```bash
# Sync every hour
0 * * * * cd /home/runner/algogpt && ./scripts/sync_github.sh >> /tmp/logs/github_sync.log 2>&1

# Sync every 6 hours
0 */6 * * * cd /home/runner/algogpt && ./scripts/sync_github.sh
```

Edit crontab:
```bash
crontab -e
```

### Option 2: Systemd Timer

Create `/etc/systemd/system/github-sync.service`:
```ini
[Unit]
Description=GitHub Sync Service
After=network.target

[Service]
Type=oneshot
User=runner
WorkingDirectory=/home/runner/algogpt
ExecStart=/home/runner/algogpt/scripts/sync_github.sh
StandardOutput=journal
StandardError=journal
```

Create `/etc/systemd/system/github-sync.timer`:
```ini
[Unit]
Description=Run GitHub sync every 6 hours

[Timer]
OnBootSec=10min
OnUnitActiveSec=6h
Persistent=true

[Install]
WantedBy=timers.target
```

Enable:
```bash
sudo systemctl enable github-sync.timer
sudo systemctl start github-sync.timer
```

### Option 3: GitHub Actions (CI/CD)

Create `.github/workflows/sync.yml`:
```yaml
name: Sync Repository

on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours
  workflow_dispatch:  # Manual trigger

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 0
          token: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Configure Git
        run: |
          git config user.name "GitHub Actions"
          git config user.email "actions@github.com"
      
      - name: Pull latest
        run: git pull origin main --rebase
      
      - name: Push if needed
        run: |
          if [ -n "$(git status --porcelain)" ]; then
            git push origin main
          fi
```

---

## Troubleshooting

### Issue: Authentication Failed

**Symptom:**
```
remote: Support for password authentication was removed on August 13, 2021.
fatal: Authentication failed
```

**Solution:**
Use Personal Access Token instead of password:
```bash
# Update remote URL
git remote set-url origin https://${GITHUB_TOKEN}@github.com/your-org/algogpt.git

# Or use SSH
git remote set-url origin git@github.com:your-org/algogpt.git
```

### Issue: Merge Conflicts

**Symptom:**
```
CONFLICT (content): Merge conflict in main.py
Automatic merge failed; fix conflicts and then commit the result.
```

**Solution:**
```bash
# 1. Check conflicted files
git status

# 2. Edit files to resolve conflicts
# Look for <<<<<<< HEAD markers

# 3. Mark as resolved
git add main.py

# 4. Complete merge
git commit -m "chore: resolve merge conflict"
```

### Issue: Large File Rejected

**Symptom:**
```
remote: error: File data/large_file.bin is 120.00 MB; this exceeds GitHub's file size limit of 100.00 MB
```

**Solution:**
```bash
# Use Git LFS for large files
git lfs install
git lfs track "*.bin"
git lfs track "data/*.db"

# Add .gitattributes
git add .gitattributes

# Re-add large file
git add data/large_file.bin
git commit -m "chore: use LFS for large files"
```

### Issue: Diverged Branches

**Symptom:**
```
Your branch and 'origin/main' have diverged
```

**Solution:**
```bash
# Option 1: Rebase (clean history)
git pull --rebase origin main

# Option 2: Merge (preserve history)
git pull origin main

# Option 3: Force push (DANGEROUS - use only if you're sure)
git push --force-with-lease origin main
```

---

## Best Practices

### 1. Commit Messages

Follow conventional commits:
```
feat: add multi-timeframe intelligence
fix: resolve trading loop bug
docs: update N8N integration guide
chore: cleanup deprecated files
refactor: optimize worker performance
```

### 2. .gitignore

Ensure sensitive files are excluded:
```gitignore
# Environment
.env
.env.local
*.secret

# Data
data/*.db
data/trades_log.json
/tmp/

# Credentials
.git-credentials
*.pem
*.key
```

### 3. Pre-commit Hooks

Create `.git/hooks/pre-commit`:
```bash
#!/bin/bash
# Pre-commit hook to prevent committing secrets

# Check for secrets
if grep -r "BINANCE_API_KEY.*=" . --exclude-dir=.git; then
    echo "❌ Error: Found API keys in files!"
    echo "Please remove secrets before committing."
    exit 1
fi

# Check for large files
find . -size +10M | grep -v ".git" | while read file; do
    echo "⚠️ Warning: Large file detected: $file"
done

echo "✅ Pre-commit checks passed"
```

### 4. Regular Sync Schedule

Sync at least:
- **Daily**: End of trading day
- **Weekly**: Full backup with tags
- **Monthly**: Create release tag

```bash
# Create monthly release
git tag -a v1.2.0 -m "Release November 2025"
git push origin v1.2.0
```

---

## Security Considerations

1. **Never commit:**
   - API keys or secrets
   - Database credentials
   - Private keys
   - User data

2. **Use environment variables** for all secrets

3. **Encrypt sensitive data** before committing

4. **Audit commits** regularly:
   ```bash
   git log -p | grep -i "api_key\|secret\|password"
   ```

5. **Rotate tokens** quarterly

---

## Useful Commands

```bash
# View commit history
git log --oneline --graph --all

# Undo last commit (keep changes)
git reset --soft HEAD~1

# Undo last commit (discard changes)
git reset --hard HEAD~1

# View differences
git diff

# Stash changes temporarily
git stash
git stash pop

# Create and apply patch
git diff > my_changes.patch
git apply my_changes.patch
```

---

**Last Updated:** November 2, 2025  
**Version:** 1.0.0  
**Maintained by:** AlgoGPT Team
