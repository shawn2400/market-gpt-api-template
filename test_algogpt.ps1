# test_algogpt.ps1
# בדיקה סופית של כל ה־endpoints אל ה־AlgoGPT API המרוחק

$baseUrl = 'https://algogpt-docker.onrender.com'

Write-Host " בדיקת GET /..."
try {
    $root = Invoke-RestMethod -Method Get -Uri "$baseUrl/"
    Write-Host "Response:" ($root | ConvertTo-Json -Depth 5)
} catch {
    Write-Error " שגיאה בבדיקה של / : $_"
}

Write-Host "`n בדיקת POST /scan..."
$scanPayload = @{
    market      = 'futures'
    min_quality = 6
    top         = 1
    trending_only   = $false
    trending_source = 'coingecko'
} | ConvertTo-Json
try {
    $scan = Invoke-RestMethod -Method Post -Uri "$baseUrl/scan" `
        -Body $scanPayload -ContentType 'application/json'
    Write-Host "Response:" ($scan | ConvertTo-Json -Depth 5)
} catch {
    Write-Error " שגיאה בבדיקה של /scan : $_"
}

Write-Host "`n בדיקת POST /ai-analyze..."
$aiPayload = @{
    rsi     = 50.0
    adx     = 25.0
    trend   = 'up'
    volume  = '1000000'
    pattern = 'none'
} | ConvertTo-Json
try {
    $ai = Invoke-RestMethod -Method Post -Uri "$baseUrl/ai-analyze" `
        -Body $aiPayload -ContentType 'application/json'
    Write-Host "Response:" ($ai | ConvertTo-Json -Depth 5)
} catch {
    Write-Error " שגיאה בבדיקה של /ai-analyze : $_"
}

Write-Host "`n בדיקת POST /calculate-quantity..."
$qtyPayload = @{
    symbol   = 'BTCUSDT'
    price    = 30000.0
    leverage = 10
    budget   = 100
} | ConvertTo-Json
try {
    $qty = Invoke-RestMethod -Method Post -Uri "$baseUrl/calculate-quantity" `
        -Body $qtyPayload -ContentType 'application/json'
    Write-Host "Response:" ($qty | ConvertTo-Json -Depth 5)
} catch {
    Write-Error " שגיאה בבדיקה של /calculate-quantity : $_"
}

Write-Host "`n כל הבדיקות בוצעו."
