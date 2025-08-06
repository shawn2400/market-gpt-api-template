<<<<<<< HEAD
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
=======
Write-Host "========== ????? ????? ??????? =========="
$files = @("main.py", "requirements.txt", "Dockerfile", ".env", "openapi.yaml")
foreach ($f in $files) {
    if (Test-Path $f) { Write-Host "$f ... OK" -ForegroundColor Green }
    else { Write-Host "$f ... ???!" -ForegroundColor Red }
}

Write-Host "`n========== ????? ?????? =========="
$dirs = @("routes", "utils")
foreach ($d in $dirs) {
    if (Test-Path $d) { Write-Host "$d ... OK" -ForegroundColor Green }
    else { Write-Host "$d ... ????!" -ForegroundColor Red }
}

Write-Host "`n========== ????? ?????? ??.env =========="
>>>>>>> 7179d67 ( הוספת נתיב /scan/multi עם Multi-TF Scan)
$envVars = @("BINANCE_API_KEY", "BINANCE_API_SECRET", "OPENAI_API_KEY")
$envLines = Get-Content .env
foreach ($v in $envVars) {
    $val = $envLines | Where-Object { $_ -match "^$v\s*=" }
    if ($val -and ($val -notmatch "=\s*$")) { Write-Host "$v ... OK" -ForegroundColor Green }
<<<<<<< HEAD
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
=======
    else { Write-Host "$v ... ??? ?? ???!" -ForegroundColor Red }
}

Write-Host "`n========== ????? pip & ?????? =========="
pip --version
pip install -r requirements.txt

Write-Host "`n========== ????? ?????? Python =========="
python -m py_compile main.py
if ($LASTEXITCODE -eq 0) { Write-Host "main.py ... OK" -ForegroundColor Green }
else { Write-Host "main.py ... ?????!" -ForegroundColor Red }

Write-Host "`n========== ????? ???? openapi.yaml =========="
>>>>>>> 7179d67 ( הוספת נתיב /scan/multi עם Multi-TF Scan)
if (Test-Path "openapi.yaml") {
    $lines = Get-Content openapi.yaml
    $hasServers = $lines | Select-String -Pattern "servers:"
    $hasPaths = $lines | Select-String -Pattern "paths:"
    if ($hasServers -and $hasPaths) { Write-Host "openapi.yaml ... OK" -ForegroundColor Green }
<<<<<<< HEAD
    else { Write-Host "openapi.yaml ... חסר שדות קריטיים!" -ForegroundColor Red }
}

Write-Host "`n========== בדיקת קישוריות לאינטרנט =========="
=======
    else { Write-Host "openapi.yaml ... ??? ???? ???????!" -ForegroundColor Red }
}

Write-Host "`n========== ????? ???????? ???????? =========="
>>>>>>> 7179d67 ( הוספת נתיב /scan/multi עם Multi-TF Scan)
try {
    $ping = Test-Connection -ComputerName "api.binance.com" -Count 1 -ErrorAction Stop
    Write-Host "Binance API Reachable ... OK" -ForegroundColor Green
} catch {
<<<<<<< HEAD
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
=======
    Write-Host "Binance API ... ?? ????!" -ForegroundColor Red
}

Write-Host "`n========== ????? ????? ???? 5000 (?????) =========="
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $tcp.Connect("127.0.0.1",5000)
    Write-Host "???? 5000 ???? (????? ??? ??)!" -ForegroundColor Yellow
    $tcp.Close()
} catch {
    Write-Host "???? 5000 ???? ... OK" -ForegroundColor Green
}

Write-Host "`n========== ????? ??????? =========="
Write-Host "?? ??? ????, ??? ???? ??Deploy!"
>>>>>>> 7179d67 ( הוספת נתיב /scan/multi עם Multi-TF Scan)
