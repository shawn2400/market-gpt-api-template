# git_sync.ps1
Write-Host "🔄 Git Sync Script - AlgoGPT Project" -ForegroundColor Cyan

# 1. הסרת קובץ env (מקומי בלבד)
if (Test-Path env) {
    Remove-Item env -Force
    Write-Host "✅ Removed local 'env' file"
}

# 2. הסרת env מהמעקב ב-Git
git rm -f --cached env 2>$null
Write-Host "✅ Ensured 'env' is not tracked"

# 3. מחיקת תיקיית rebase-merge אם יש
if (Test-Path ".git/rebase-merge") {
    Remove-Item -Recurse -Force ".git/rebase-merge"
    Write-Host "✅ Removed stuck rebase-merge folder"
}

# 4. משיכת עדכונים מהענן
git fetch origin
Write-Host "✅ Fetched latest from origin"

# 5. סנכרון מלא לענן (דריסה ל-main)
git reset --hard origin/main
Write-Host "✅ Reset local branch to origin/main"

# 6. הוספת שינויים מקומיים (אם יש)
git add .
if (-not (git diff --cached --quiet)) {
    git commit -m "Auto-sync local changes"
    Write-Host "✅ Committed local changes"
} else {
    Write-Host "ℹ No local changes to commit"
}

# 7. דחיפה לענן
git push origin main
Write-Host "🚀 Push complete"

Write-Host "✅ Git sync finished successfully" -ForegroundColor Green
