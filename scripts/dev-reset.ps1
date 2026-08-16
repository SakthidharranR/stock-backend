# Resets local Docker Postgres, runs migrations, and syncs Cognito users into Postgres.
# Requires: Docker Desktop, Python 3.12+, AWS CLI credentials (aws configure) with cognito-idp:ListUsers.
#
# Usage (from stock-backend):
#   .\scripts\dev-reset.ps1
#   .\scripts\dev-reset.ps1 -WipeData          # also delete postgres volume (fresh DB)
#   .\scripts\dev-reset.ps1 -SkipSync          # skip Cognito sync
#   .\scripts\dev-reset.ps1 -NoIdentity        # postgres only (run identity with uvicorn locally)
#   .\scripts\dev-reset.ps1 -Local             # no Docker - uvicorn + DATABASE_URL from .env
#   .\scripts\dev-reset.ps1 -StartDocker       # try launching Docker Desktop, then continue

param(
    [switch]$WipeData,
    [switch]$SkipSync,
    [switch]$NoIdentity,
    [switch]$Local,
    [switch]$StartDocker
)

$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path -Parent $PSScriptRoot
$IdentityDir = Join-Path $BackendRoot "services\identity"
$MarketDir = Join-Path $BackendRoot "services\market"
$MigrationsDir = Join-Path $BackendRoot "migrations"
$IdentityMigration = Join-Path $IdentityDir "migrations\001_users.sql"

Set-Location $BackendRoot

Write-Host "dev-reset.ps1 (Python identity)" -ForegroundColor DarkGray

function Ensure-BackendEnv {
    $envFile = Join-Path $BackendRoot ".env"
    $exampleFile = Join-Path $BackendRoot ".env.example"
    if (Test-Path $envFile) { return }

    if (-not (Test-Path $exampleFile)) {
        throw "Missing stock-backend/.env and .env.example. Copy .env.example to .env and set FINNHUB_API_KEY."
    }

    Copy-Item $exampleFile $envFile
    Write-Host "Created stock-backend/.env from .env.example - add your FINNHUB_API_KEY before live quotes." -ForegroundColor Yellow
}

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Write-DockerHelp {
    Write-Host ""
    Write-Host "Docker engine is not responding." -ForegroundColor Red
    Write-Host "If Images/Containers show 'An error occurred while loading', the engine crashed." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Fix:" -ForegroundColor Yellow
    Write-Host "  1. Docker Desktop -> Troubleshoot (bug icon) -> Restart"
    Write-Host "  2. Wait until status is Running (not 'Starting the Docker Engine...')"
    Write-Host "  3. Re-run:  .\scripts\dev-reset.ps1 -SkipSync"
    Write-Host ""
    Write-Host "Or retry with auto-start:" -ForegroundColor Yellow
    Write-Host "  .\scripts\dev-reset.ps1 -SkipSync -StartDocker"
    Write-Host ""
    Write-Host "No Docker? Run identity locally (needs Postgres reachable via DATABASE_URL in .env):" -ForegroundColor Yellow
    Write-Host "  .\scripts\dev-reset.ps1 -Local -SkipSync"
    Write-Host ""
    Write-Host "Docker still broken on Windows? Try (Admin PowerShell):" -ForegroundColor Yellow
    Write-Host "  .\scripts\fix-wsl-docker.ps1"
    Write-Host ""
}

function Test-DockerDaemon {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        # docker ps proves the engine API works (docker info can lie when UI is half-up)
        docker ps *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Invoke-DockerCompose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeArgs
    )

    if (-not (Test-DockerDaemon)) {
        Write-DockerHelp
        throw "Docker engine is not responding. If Docker Desktop shows image/list errors, use Troubleshoot -> Restart or run fix-wsl-docker.ps1 as Admin."
    }

    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & docker compose @ComposeArgs | Out-Host
        $exitCode = $LASTEXITCODE
        return $exitCode
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Wait-Container {
    param(
        [string]$Name,
        [int]$TimeoutSeconds = 45
    )

    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
            $status = & docker inspect $Name --format '{{.State.Status}}' 2>$null
            if ($LASTEXITCODE -eq 0 -and $status -eq 'running') { return $true }
            Start-Sleep -Seconds 1
        }
        return $false
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Wait-IdentityContainer {
    Wait-Container -Name "stock-identity"
}

function Test-ServiceHealth {
    param(
        [string]$Url,
        [int]$Retries = 15
    )

    for ($i = 0; $i -lt $Retries; $i++) {
        try {
            $response = Invoke-RestMethod -Uri $Url -TimeoutSec 2
            if ($response.status -eq "ok") {
                Write-Host "Health check OK: $Url" -ForegroundColor Green
                return $true
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    Write-Warning "Health check failed for $Url"
    return $false
}

function Invoke-ComposeDown {
    if (-not (Test-DockerDaemon)) {
        Write-Host "Docker engine not available - skipping compose down." -ForegroundColor Yellow
        return
    }

    $args = @("down", "--remove-orphans")
    if ($WipeData) { $args = @("down", "-v", "--remove-orphans") }

    $code = Invoke-DockerCompose -ComposeArgs $args
    if ($code -ne 0) {
        Write-Host "compose down returned exit code $code (continuing anyway)." -ForegroundColor Yellow
    }
}

function Start-DockerDesktop {
    $candidates = @(
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) {
            Write-Host "Launching Docker Desktop..."
            Start-Process $path | Out-Null
            return $true
        }
    }
    return $false
}

function Wait-DockerDaemon {
    param([int]$TimeoutSeconds = 180)

    for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
        if (Test-DockerDaemon) { return $true }
        if ($i % 10 -eq 0) {
            Write-Host ("Waiting for Docker daemon... ({0}s)" -f $i)
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Ensure-Docker {
    if (Test-DockerDaemon) { return }

    if ($StartDocker) {
        Write-Step "Docker engine not ready - attempting to start Docker Desktop"
        if (-not (Start-DockerDesktop)) {
            Write-DockerHelp
            throw "Docker Desktop executable not found."
        }
        if (-not (Wait-DockerDaemon -TimeoutSeconds 180)) {
            Write-DockerHelp
            throw "Docker Desktop did not become ready within 180 seconds."
        }
        return
    }

    Write-DockerHelp
    throw "Docker engine is not responding. Wait until Docker Desktop shows Running (not 'Starting...'), then re-run."
}

function Stop-LocalDevServer($port) {
    # Only kill local dev servers (python/uvicorn). Never kill Docker port-forward processes.
    $allowKill = @('python', 'pythonw', 'py', 'uvicorn', 'identity', 'go', 'node')
    $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if (-not $connections) { return }
    $connections | ForEach-Object {
        $procId = $_.OwningProcess
        if (-not $procId -or $procId -eq 0) { return }
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if (-not $proc) { return }
        if ($allowKill -notcontains $proc.ProcessName) {
            Write-Host "Leaving $($proc.ProcessName) (pid $procId) on port $port"
            return
        }
        Write-Host "Stopping local $($proc.ProcessName) (pid $procId) on port $port"
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}

function Get-AwsExe {
    $paths = @(
        "C:\Program Files\Amazon\AWSCLIV2\aws.exe",
        "$env:ProgramFiles\Amazon\AWSCLIV2\aws.exe"
    )
    foreach ($p in $paths) {
        if (Test-Path $p) { return $p }
    }
    $cmd = Get-Command aws -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Test-AwsCredentials {
    $aws = Get-AwsExe
    if (-not $aws) { return $false }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        & $aws sts get-caller-identity *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Get-PythonExe {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) { return "py -3" }
    return $null
}

function Invoke-Python {
    param([string[]]$PythonArgs)

    $python = Get-PythonExe
    if (-not $python) {
        throw "Python not found. Install Python 3.12+ and ensure it is on PATH."
    }
    if ($python -eq "py -3") {
        & py -3 @PythonArgs
    } else {
        & $python @PythonArgs
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($PythonArgs -join ' ')"
    }
}

function Test-FinnhubKeyConfigured {
    $envFile = Join-Path $BackendRoot ".env"
    if (-not (Test-Path $envFile)) { return $false }

    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*FINNHUB_API_KEY\s*=\s*(.+)\s*$') {
            $key = $Matches[1].Trim().Trim('"').Trim("'")
            if (-not $key) { return $false }
            if ($key.Length -lt 10) { return $false }
            if ($key.StartsWith("your_")) { return $false }
            return $true
        }
    }
    return $false
}

function Install-ServicePythonDeps {
    param([string]$ServiceDir)

    Set-Location $ServiceDir
    Invoke-Python @("-m", "pip", "install", "-q", "-r", "requirements.txt")
    Set-Location $BackendRoot
}

function Install-IdentityPythonDeps {
    Install-ServicePythonDeps -ServiceDir $IdentityDir
}

function Start-LocalIdentity {
    Write-Step "Starting identity service locally (no Docker)"
    Stop-LocalDevServer 8081
    Install-IdentityPythonDeps

    $envFile = Join-Path $IdentityDir ".env"
    $backendEnv = Join-Path $BackendRoot ".env"
    if (-not $env:DATABASE_URL) {
        if (Test-Path $envFile) {
            Get-Content $envFile | ForEach-Object {
                if ($_ -match '^\s*DATABASE_URL\s*=\s*(.+)\s*$') {
                    $env:DATABASE_URL = $Matches[1].Trim()
                }
            }
        } elseif (Test-Path $backendEnv) {
            Get-Content $backendEnv | ForEach-Object {
                if ($_ -match '^\s*DATABASE_URL\s*=\s*(.+)\s*$') {
                    $env:DATABASE_URL = $Matches[1].Trim()
                }
            }
        }
    }

    if (-not $env:DATABASE_URL) {
        throw "DATABASE_URL is not set. Add it to stock-backend/.env or services/identity/.env"
    }

    if (-not $env:PORT) { $env:PORT = "8081" }

    Write-Host "DATABASE_URL loaded. Starting uvicorn on port $($env:PORT)..." -ForegroundColor Green
    Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow
    Set-Location $IdentityDir
    Invoke-Python @(
        "-m", "uvicorn", "app.main:create_application",
        "--factory", "--host", "0.0.0.0", "--port", $env:PORT
    )
}

function Test-IdentityHealth {
    Test-ServiceHealth -Url "http://localhost:8081/health"
}

Ensure-BackendEnv

if ($Local) {
    if (-not $SkipSync) {
        Write-Host "Note: -Local skips Cognito sync unless you run scripts/sync_cognito.py yourself." -ForegroundColor Yellow
    }
    Start-LocalIdentity
    exit 0
}

Ensure-Docker

Write-Step "Stopping Docker Compose services"
Invoke-ComposeDown

Write-Step "Starting Postgres"
$code = Invoke-DockerCompose -ComposeArgs @("up", "-d", "postgres")
if ($code -ne 0) { throw "Failed to start Postgres container" }

Write-Step "Waiting for Postgres to be ready"
$ready = $false
for ($i = 0; $i -lt 45; $i++) {
    docker exec stock-postgres pg_isready -U stockapp -d stockapp 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $ready) {
    throw "Postgres did not become ready in time."
}

Write-Step "Running migrations"
$migrationFiles = @($IdentityMigration)
if (Test-Path $MigrationsDir) {
    $migrationFiles += Get-ChildItem -Path $MigrationsDir -Filter "*.sql" | Sort-Object Name | ForEach-Object { $_.FullName }
}
foreach ($file in $migrationFiles) {
    if (-not (Test-Path $file)) {
        throw "Migration file not found: $file"
    }
    Write-Host "Applying $(Split-Path $file -Leaf)..." -ForegroundColor DarkGray
    Get-Content $file -Raw | docker exec -i stock-postgres psql -U stockapp -d stockapp -v ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) {
        throw "Migration failed: $file"
    }
}

if (-not $SkipSync) {
    if (-not (Test-AwsCredentials)) {
        Write-Host ""
        Write-Host "Skipping Cognito sync - AWS credentials not configured." -ForegroundColor Yellow
        Write-Host "Run once:  .\scripts\configure-aws.ps1" -ForegroundColor Yellow
        Write-Host "Or skip:   .\scripts\dev-reset.ps1 -SkipSync" -ForegroundColor Yellow
    } else {
        Write-Step "Syncing Cognito user pool to Postgres"
        Install-IdentityPythonDeps
        Set-Location $IdentityDir
        Invoke-Python @("scripts/sync_cognito.py")
        Set-Location $BackendRoot
    }
} else {
    Write-Host "Skipped Cognito sync (-SkipSync)" -ForegroundColor Yellow
}

if (-not $NoIdentity) {
    Write-Step "Building and starting microservices"
    Ensure-Docker
    $composeCode = Invoke-DockerCompose -ComposeArgs @("up", "-d", "--build", "identity", "market", "portfolio")
    if ($composeCode -ne 0) {
        Write-Host "docker compose up failed (exit $composeCode)." -ForegroundColor Red
        Write-Host "Check: stock-backend/.env exists, Docker Desktop is Running, and ports 8081-8083 are free." -ForegroundColor Yellow
        throw "Failed to start microservice containers"
    }
    foreach ($name in @("stock-identity", "stock-market", "stock-portfolio")) {
        if (-not (Wait-Container -Name $name)) {
            Write-Host "$name container logs:" -ForegroundColor Yellow
            $prev = $ErrorActionPreference
            $ErrorActionPreference = "SilentlyContinue"
            try {
                docker logs $name --tail 30
            } finally {
                $ErrorActionPreference = $prev
            }
            throw "$name container did not reach running state"
        }
    }
    Start-Sleep -Seconds 2
    Test-ServiceHealth -Url "http://localhost:8081/health" | Out-Null
    Test-ServiceHealth -Url "http://localhost:8082/health" | Out-Null
    Test-ServiceHealth -Url "http://localhost:8083/health" | Out-Null

    if (Test-FinnhubKeyConfigured) {
        Write-Step "Syncing Finnhub US symbols"
        Install-ServicePythonDeps -ServiceDir $MarketDir
        Set-Location $MarketDir
        try {
            Invoke-Python @("scripts/sync_symbols.py")
        } catch {
            Write-Host "Symbol sync failed (seeded symbols still available)." -ForegroundColor Yellow
        }
        Set-Location $BackendRoot
    } else {
        Write-Host "Skipping Finnhub symbol sync - add a real FINNHUB_API_KEY to stock-backend/.env for live quotes." -ForegroundColor DarkGray
    }
} else {
    Write-Host ""
    Write-Host "Identity container skipped (-NoIdentity). Run locally with:" -ForegroundColor Yellow
    Write-Host "  .\scripts\dev-reset.ps1 -Local -SkipSync" -ForegroundColor Yellow
}

Write-Step "Done"
if (Test-DockerDaemon) {
    docker compose ps
} else {
    Write-Host "Docker engine stopped before final status check." -ForegroundColor Yellow
}
