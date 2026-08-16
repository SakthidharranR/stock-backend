# One-shot: wait for Docker, then start Postgres + Python identity API.
#
# If Docker shows errors / "Starting the Docker Engine..." forever:
#   1. Open PowerShell AS ADMINISTRATOR
#   2. cd to stock-backend
#   3. .\scripts\fix-wsl-docker.ps1
#   4. Come back here and run: .\scripts\start-dev.ps1
#
# Usage (normal PowerShell):
#   .\scripts\start-dev.ps1
#   .\scripts\start-dev.ps1 -SkipSync

param(
    [switch]$SkipSync = $true
)

$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path -Parent $PSScriptRoot
Set-Location $BackendRoot

function Test-DockerEngine {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        docker ps *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $prev
    }
}

Write-Host ""
Write-Host "=== Stock App: start dev stack ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-DockerEngine)) {
    Write-Host "Docker engine is not responding yet." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "If Docker Desktop shows an error or is stuck on 'Starting the Docker Engine...':" -ForegroundColor Yellow
    Write-Host "  1. Quit Docker Desktop (whale icon -> Quit)"
    Write-Host "  2. Open PowerShell as Administrator"
    Write-Host "  3. cd `"$BackendRoot`""
    Write-Host "  4. .\scripts\fix-wsl-docker.ps1"
    Write-Host "  5. Wait for 'Docker engine is running', then run this script again"
    Write-Host ""
    Write-Host "Otherwise, trying to launch Docker Desktop and wait (up to 3 min)..." -ForegroundColor Yellow

    $dockerExe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerExe) {
        Start-Process $dockerExe | Out-Null
    }

    $ready = $false
    for ($i = 0; $i -lt 180; $i++) {
        if (Test-DockerEngine) {
            $ready = $true
            Write-Host "Docker ready after ${i}s" -ForegroundColor Green
            break
        }
        if ($i % 15 -eq 0) { Write-Host "  waiting... ${i}s" }
        Start-Sleep -Seconds 1
    }

    if (-not $ready) {
        Write-Host ""
        Write-Host "Docker still not ready. Run fix-wsl-docker.ps1 as Admin (steps above)." -ForegroundColor Red
        exit 1
    }
}

& "$PSScriptRoot\dev-reset.ps1" -SkipSync:$SkipSync

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "=== Ready ===" -ForegroundColor Green
Write-Host "  Identity:  http://localhost:8081/health"
Write-Host "  Market:    http://localhost:8082/health"
Write-Host "  Portfolio: http://localhost:8083/health"
Write-Host "  Frontend: npm run dev  (in stock-frontend)"
Write-Host ""
foreach ($url in @(
    "http://localhost:8081/health",
    "http://localhost:8082/health",
    "http://localhost:8083/health"
)) {
    try {
        $health = Invoke-RestMethod -Uri $url -TimeoutSec 5
        Write-Host "Health check $($health.status): $url" -ForegroundColor Green
    } catch {
        Write-Host "Health check failed: $url" -ForegroundColor Yellow
    }
}
