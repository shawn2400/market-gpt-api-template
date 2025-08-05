Write-Host "========== בדיקת קבצים קריטיים =========="
$files = @("main.py", "requirements.txt", "Dockerfile", ".env", "openapi.yaml")
foreach ($f in $files) {
    if (Test-Path $f) { Write-Host "$f ... OK" -ForegroundColor Green }
    else { Write-Host "$f ... חסר!" -ForegroundColor Red }
}

Write-Host "`n========== בדיקת תיקיות =========="
$dirs = @("routes", "utils")
foreach ($d in $dirs) {
    if (Test-Path $d) { Write-Host "$d ... OK" -ForegroundColor Green }
    else { Write-Host "$d ... חסרה!" -ForegroundColor Red }
}

Write-Host "`n========== בדיקת מפתחות ב־.env =========="
$envVars = @("BINANCE_API_KEY", "BINANCE_API_SECRET", "OPENAI_API_KEY")
$envLines = Get-Content .env
foreach ($v in $envVars) {
    $val = $envLines | Where-Object { $_ -match "^$v\s*=" }
    if ($val -and ($val -notmatch "=\s*$")) { Write-Host "$v ... OK" -ForegroundColor Green }
    else { Write-Host "$v ... חסר או ריק!" -ForegroundColor Red }
}

Write-Host "`n========== בדיקת pip & תלויות =========="
pip --version
pip install -r requirements.txt

Write-Host "`n========== בדיקת סינטקס Python =========="
python -m py_compile main.py
if ($LASTEXITCODE -eq 0) { Write-Host "main.py ... OK" -ForegroundColor Green }
else { Write-Host "main.py ... שגיאה!" -ForegroundColor Red }

Write-Host "`n========== בדיקת קובץ openapi.yaml =========="
if (Test-Path "openapi.yaml") {
    $lines = Get-Content openapi.yaml
    $hasServers = $lines | Select-String -Pattern "servers:"
    $hasPaths = $lines | Select-String -Pattern "paths:"
    if ($hasServers -and $hasPaths) { Write-Host "openapi.yaml ... OK" -ForegroundColor Green }
    else { Write-Host "openapi.yaml ... חסר שדות קריטיים!" -ForegroundColor Red }
}

Write-Host "`n========== בדיקת קישוריות לאינטרנט =========="
try {
    $ping = Test-Connection -ComputerName "api.binance.com" -Count 1 -ErrorAction Stop
    Write-Host "Binance API Reachable ... OK" -ForegroundColor Green
} catch {
    Write-Host "Binance API ... לא נגיש!" -ForegroundColor Red
}

Write-Host "`n========== בדיקת פתיחת פורט 5000 (מקומי) =========="
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $tcp.Connect("127.0.0.1",5000)
    Write-Host "פורט 5000 פתוח (כנראה שרת רץ)!" -ForegroundColor Yellow
    $tcp.Close()
} catch {
    Write-Host "פורט 5000 פנוי ... OK" -ForegroundColor Green
}

Write-Host "`n========== בדיקה הסתיימה =========="
Write-Host "אם הכל ירוק, אתה מוכן ל־Deploy!"
