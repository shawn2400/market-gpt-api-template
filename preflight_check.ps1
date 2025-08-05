Write-Host "=========== בדיקת מוכנות AlgoGPT ==========="
$ok = $true

# קבצים בסיסיים
$mustFiles = @("main.py",".env","openapi.yaml","requirements.txt")
foreach ($f in $mustFiles) {
    if (Test-Path $f) { Write-Host "$f ... OK" -ForegroundColor Green }
    else { Write-Host "$f ... חסר!" -ForegroundColor Red; $ok = $false }
}

# תיקיות מרכזיות
$mustDirs = @("routes","utils")
foreach ($d in $mustDirs) {
    if (Test-Path $d) { Write-Host "$d ... OK" -ForegroundColor Green }
    else { Write-Host "$d ... חסרה!" -ForegroundColor Red; $ok = $false }
}

# בדיקת משתני סביבה
$envVars = @("BINANCE_API_KEY", "BINANCE_API_SECRET", "OPENAI_API_KEY")
$envLines = Get-Content .env
foreach ($v in $envVars) {
    $val = $envLines | Where-Object { $_ -match "^$v\s*=" }
    if ($val -and ($val -notmatch "=\s*$")) { Write-Host "$v ... OK" -ForegroundColor Green }
    else { Write-Host "$v ... חסר או ריק!" -ForegroundColor Red; $ok = $false }
}

# בדיקת pip dependencies
try {
    pip --version > $null
    pip install -r requirements.txt
    Write-Host "pip dependencies ... OK" -ForegroundColor Green
} catch {
    Write-Host "pip dependencies ... בעיה!" -ForegroundColor Red; $ok = $false
}

# בדיקת סינטקס לכל קבצי py ראשיים (כולל routes/utils)
$pyFiles = @("main.py") + (Get-ChildItem -Path routes\*.py).Name + (Get-ChildItem -Path utils\*.py).Name
foreach ($py in $pyFiles) {
    try {
        python -m py_compile $py
        Write-Host "$py ... OK" -ForegroundColor Green
    } catch {
        Write-Host "$py ... שגיאת סינטקס!" -ForegroundColor Red; $ok = $false
    }
}

# בדיקת יבוא מודולים קריטיים
Write-Host "בודק יבוא של מודולים עיקריים..."
$pyCmd = @'
try:
    import fastapi, openai, requests, pandas
    from dotenv import load_dotenv
    from routes.ai import router as ai_router
    from routes.trade import router as trade_router
    from routes.grid import router as grid_router
    from routes.multi_scan import router as multi_scan_router
    from utils.ws_fallback import launch_multi_websocket, get_price
    print("Python imports ... OK")
except Exception as e:
    print("Python import FAIL:", e)
'@
$res = python -c $pyCmd
if ($res -like "*OK") {
    Write-Host "יבוא מודולים ... OK" -ForegroundColor Green
} else {
    Write-Host $res -ForegroundColor Red
    $ok = $false
}

# בדיקת קובץ openapi.yaml
if (Test-Path "openapi.yaml") {
    $lines = Get-Content openapi.yaml
    if (($lines | Select-String -Pattern "servers:") -and ($lines | Select-String -Pattern "paths:")) {
        Write-Host "openapi.yaml ... OK" -ForegroundColor Green
    } else {
        Write-Host "openapi.yaml ... חסר שדות קריטיים!" -ForegroundColor Red; $ok = $false
    }
} else {
    Write-Host "openapi.yaml ... חסר!" -ForegroundColor Red; $ok = $false
}

# בדיקת קישוריות לאינטרנט (Binance)
try {
    $binance = Invoke-WebRequest -Uri "https://api.binance.com/api/v3/ping" -UseBasicParsing -TimeoutSec 5
    Write-Host "Binance API ... OK" -ForegroundColor Green
} catch {
    Write-Host "Binance API ... לא נגיש!" -ForegroundColor Red; $ok = $false
}

# בדיקת קישוריות כללית (OpenAI HEADERS לא חובה)
try {
    $openai = Invoke-WebRequest -Uri "https://api.openai.com/v1/models" -UseBasicParsing -TimeoutSec 5
    if ($openai.StatusCode -eq 401 -or $openai.StatusCode -eq 200) {
        Write-Host "OpenAI API ... OK (נגיש/דורש הרשאה)" -ForegroundColor Green
    } else {
        Write-Host "OpenAI API ... לא נגיש!" -ForegroundColor Red; $ok = $false
    }
} catch {
    Write-Host "OpenAI API ... לא נגיש!" -ForegroundColor Red; $ok = $false
}

Write-Host "=========== דוח סופי ==========="
if ($ok) {
    Write-Host "🟢 הכול תקין. מוכן ל־Render וסחר אמיתי!" -ForegroundColor Green
} else {
    Write-Host "🔴 יש בעיות. ראה למעלה – תקן לפני Deploy!" -ForegroundColor Red
}
