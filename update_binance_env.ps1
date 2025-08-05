# קובץ env לבחירתך
$envPath = ".env"

if (-not (Test-Path $envPath)) {
    Write-Error "קובץ $envPath לא נמצא בספריה הנוכחית."
    exit 1
}

# קריאת כל השורות
$lines = Get-Content $envPath

# משתנים לעדכון
$keys = @("BINANCE_API_KEY", "BINANCE_API_SECRET")
$newLines = @()

foreach ($line in $lines) {
    $found = $false
    foreach ($key in $keys) {
        if ($line -match "^$key\s*=") {
            $current = $line.Split("=",2)[1].Trim()
            Write-Host "$key הנוכחי: $current"
            $val = Read-Host "הזן ערך חדש עבור $key (Enter = להשאיר קיים)"
            if ($val -eq "") { $val = $current }
            $newLines += "$key=$val"
            $found = $true
            break
        }
    }
    if (-not $found) { $newLines += $line }
}

# שמירה חזרה
Set-Content $envPath $newLines
Write-Host "✔️ המפתחות עודכנו בהצלחה."
