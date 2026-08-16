# Run as Administrator (right-click PowerShell -> Run as administrator)
# Fixes Docker Desktop stuck on "Starting the Docker Engine..."

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

Write-Step "Stopping Docker Desktop and WSL"
Stop-Process -Name "Docker Desktop","com.docker.backend" -Force -ErrorAction SilentlyContinue
wsl --shutdown
Start-Sleep -Seconds 5

Write-Step "Restarting Windows container / Hyper-V services"
$stopOrder = @("com.docker.service", "hns", "vmcompute")
$startOrder = @("vmcompute", "hns", "com.docker.service")

foreach ($svc in $stopOrder) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($s -and $s.Status -eq "Running") {
        Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue
        Write-Host "  stopped $svc"
    }
}

Start-Sleep -Seconds 3

foreach ($svc in $startOrder) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if (-not $s) { continue }
    try {
        if ($s.Status -ne "Running") {
            Start-Service -Name $svc -ErrorAction Stop
        }
        $s = Get-Service -Name $svc
        Write-Host "  $($s.Name): $($s.Status)" -ForegroundColor $(if ($s.Status -eq "Running") { "Green" } else { "Red" })
    } catch {
        Write-Host "  FAILED to start ${svc}: $_" -ForegroundColor Red
    }
}

if (Test-Path "$env:USERPROFILE\.wslconfig") {
    Write-Host ""
    Write-Host ".wslconfig found at $env:USERPROFILE\.wslconfig" -ForegroundColor Yellow
    Get-Content "$env:USERPROFILE\.wslconfig"
    Write-Host "If Docker still hangs, temporarily rename .wslconfig and reboot." -ForegroundColor Yellow
}

Write-Step "Testing WSL docker-desktop distro"
$result = wsl -d docker-desktop -- echo wsl-ok 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "WSL docker-desktop: OK" -ForegroundColor Green
} else {
    Write-Host "WSL docker-desktop: FAILED" -ForegroundColor Red
    Write-Host $result
    Write-Host ""
    Write-Host "Common fixes (try in order):" -ForegroundColor Yellow
    Write-Host "  1. Restart Windows (fixes most stuck-engine cases)"
    Write-Host "  2. Windows Security -> Device security -> Core isolation"
    Write-Host "     Turn OFF 'Memory integrity', reboot"
    Write-Host "  3. Control Panel -> Power -> Choose what power buttons do"
    Write-Host "     Turn OFF 'Turn on fast startup', reboot"
    Write-Host "  4. Docker Desktop -> Troubleshoot (bug icon) -> Restart / Reset to factory defaults"
    Write-Host "  5. Settings -> Apps -> Installed apps -> Docker Desktop -> Modify -> Repair"
    Write-Host ""
    Write-Host "Work on Stock App without Docker:" -ForegroundColor Yellow
    Write-Host "  .\scripts\run-local-dev.ps1"
    exit 1
}

Write-Step "Starting Docker Desktop"
$dockerExe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
if (-not (Test-Path $dockerExe)) {
    throw "Docker Desktop not found at $dockerExe"
}
Start-Process $dockerExe

Write-Step "Waiting for Docker engine (up to 3 minutes)"
$ready = $false
for ($i = 0; $i -lt 180; $i++) {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) {
        $ready = $true
        break
    }
    if ($i % 15 -eq 0) { Write-Host "  still starting... ($i s)" }
    Start-Sleep -Seconds 1
}

if ($ready) {
    Write-Host ""
    Write-Host "Docker engine is running." -ForegroundColor Green
    docker version
    Write-Host ""
    Write-Host "Next: cd stock-backend; .\scripts\dev-reset.ps1 -SkipSync" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Docker engine still not ready after 3 minutes." -ForegroundColor Red
    Write-Host "Check logs: $env:LOCALAPPDATA\Docker\log\host\com.docker.backend.exe.log" -ForegroundColor Yellow
    Write-Host "Or use: .\scripts\run-local-dev.ps1" -ForegroundColor Yellow
    exit 1
}
