$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$envPath = Join-Path $repoRoot ".env"
if (-not (Test-Path -LiteralPath $envPath)) {
  Copy-Item -LiteralPath (Join-Path $repoRoot ".env.example") -Destination $envPath
}

$settings = @{}
$envLines = Get-Content -LiteralPath $envPath
foreach ($line in $envLines) {
  $entry = $line.Trim().TrimStart([char]0xFEFF)
  if (-not $entry -or $entry.StartsWith("#")) { continue }
  if ($entry -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
    $name = $Matches[1]
    $value = $Matches[2].Trim()
    if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    $settings[$name] = $value
  }
}

$changed = $false
if ([string]::IsNullOrWhiteSpace($settings["CAREERPILOT_PASSWORD"])) {
  $securePassword = Read-Host "CareerPilot giriş şifrenizi belirleyin (bir kez)" -AsSecureString
  $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
  try { $settings["CAREERPILOT_PASSWORD"] = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer) }
  if ([string]::IsNullOrWhiteSpace($settings["CAREERPILOT_PASSWORD"])) { throw "Şifre boş olamaz." }
  $changed = $true
}

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { $python = "python" }
if ([string]::IsNullOrWhiteSpace($settings["CAREERPILOT_SESSION_SECRET"])) {
  $settings["CAREERPILOT_SESSION_SECRET"] = (& $python -c "import secrets; print(secrets.token_urlsafe(48))").Trim()
  if ($LASTEXITCODE -ne 0 -or $settings["CAREERPILOT_SESSION_SECRET"].Length -lt 16) { throw "Oturum anahtarı üretilemedi. Python kurulumunu kontrol edin." }
  $changed = $true
}

# Local machine is the reliable fetch environment for sources that block data centers.
# Existing .env files without a value get a stable 12-hour interval; set it to 0 to disable.
if (-not $settings.ContainsKey("CAREERPILOT_SYNC_INTERVAL_HOURS")) {
  $settings["CAREERPILOT_SYNC_INTERVAL_HOURS"] = "12"
}

if ($changed) {
  $updatedLines = [System.Collections.Generic.List[string]]::new()
  $written = @{}
  foreach ($line in $envLines) {
    if ($line -match '^\uFEFF?\s*(CAREERPILOT_PASSWORD|CAREERPILOT_SESSION_SECRET)=') {
      $name = $Matches[1]
      $updatedLines.Add("$name=$($settings[$name])")
      $written[$name] = $true
    } else { $updatedLines.Add($line) }
  }
  foreach ($name in @("CAREERPILOT_PASSWORD", "CAREERPILOT_SESSION_SECRET")) {
    if (-not $written.ContainsKey($name)) { $updatedLines.Add("$name=$($settings[$name])") }
  }
  [System.IO.File]::WriteAllLines($envPath, $updatedLines, [System.Text.UTF8Encoding]::new($false))
}

foreach ($name in $settings.Keys) {
  [Environment]::SetEnvironmentVariable($name, $settings[$name], "Process")
}
& $python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
