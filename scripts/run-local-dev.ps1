# Run the Python identity API without Docker.
# You still need Postgres reachable at DATABASE_URL (local install, cloud, or Docker once fixed).
#
# Usage (from stock-backend):
#   .\scripts\run-local-dev.ps1

$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path -Parent $PSScriptRoot
$IdentityDir = Join-Path $BackendRoot "services\identity"
$MigrationFile = Join-Path $IdentityDir "migrations\001_users.sql"

Set-Location $BackendRoot

function Load-DatabaseUrl {
    if ($env:DATABASE_URL) { return $env:DATABASE_URL.Trim() }
    foreach ($path in @(
        (Join-Path $IdentityDir ".env"),
        (Join-Path $BackendRoot ".env")
    )) {
        if (-not (Test-Path $path)) { continue }
        Get-Content $path | ForEach-Object {
            if ($_ -match '^\s*DATABASE_URL\s*=\s*(.+)\s*$') {
                return $Matches[1].Trim()
            }
        }
    }
    return $null
}

$dbUrl = Load-DatabaseUrl
if (-not $dbUrl) {
    Write-Host "DATABASE_URL not found." -ForegroundColor Red
    Write-Host ""
    Write-Host "Add to stock-backend\.env (copy from .env.example):" -ForegroundColor Yellow
    Write-Host "  DATABASE_URL=postgres://stockapp:stockapp_dev@localhost:5433/stockapp?sslmode=disable"
    Write-Host ""
    Write-Host "Options for Postgres without Docker Desktop:" -ForegroundColor Yellow
    Write-Host "  - Install PostgreSQL for Windows: https://www.postgresql.org/download/windows/"
    Write-Host "  - Use a free cloud DB (Neon, Supabase) and paste its connection string"
    Write-Host "  - Fix Docker, then run .\scripts\dev-reset.ps1 -SkipSync"
    exit 1
}

$env:DATABASE_URL = $dbUrl
if (-not $env:PORT) { $env:PORT = "8081" }

Write-Host "Using DATABASE_URL from .env" -ForegroundColor Green

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python not found. Install Python 3.11+ and add it to PATH."
}

Set-Location $IdentityDir
& python -m pip install -q -r requirements.txt

Write-Host ""
Write-Host "Tip: run migration once if users table is missing:" -ForegroundColor Yellow
Write-Host "  psql `"$dbUrl`" -f migrations\001_users.sql"
Write-Host ""
Write-Host "Starting identity API on http://localhost:$($env:PORT)" -ForegroundColor Green
Write-Host "Health: http://localhost:$($env:PORT)/health" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow
Write-Host ""

& python -m uvicorn app.main:create_application --factory --host 0.0.0.0 --port $env:PORT
