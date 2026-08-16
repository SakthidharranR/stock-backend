# One-time AWS setup for Cognito sync (ListUsers).
# Usage:
#   .\scripts\configure-aws.ps1
#   .\scripts\configure-aws.ps1 -AccessKeyId AKIA... -SecretAccessKey 'your-secret'

param(
    [string]$AccessKeyId,
    [string]$SecretAccessKey,
    [string]$Region = "us-east-1"
)

$ErrorActionPreference = "Stop"
$AwsExe = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"

if (-not (Test-Path $AwsExe)) {
    Write-Host "AWS CLI not found. Installing..." -ForegroundColor Yellow
    winget install Amazon.AWSCLI --accept-package-agreements --accept-source-agreements
    if (-not (Test-Path $AwsExe)) {
        throw "AWS CLI install failed. Restart terminal and try again."
    }
}

Write-Host ""
Write-Host "Create an access key in AWS Console:" -ForegroundColor Cyan
Write-Host "  IAM -> Users -> your user -> Security credentials -> Create access key" -ForegroundColor Gray
Write-Host "  (Programmatic access is fine for local dev)" -ForegroundColor Gray
Write-Host ""

if (-not $AccessKeyId) {
    $AccessKeyId = Read-Host "AWS Access Key ID"
}
if (-not $SecretAccessKey) {
    $SecretAccessKey = Read-Host "AWS Secret Access Key"
}

& $AwsExe configure set aws_access_key_id $AccessKeyId
& $AwsExe configure set aws_secret_access_key $SecretAccessKey
& $AwsExe configure set default.region $Region
& $AwsExe configure set default.output json

Write-Host ""
Write-Host "Testing credentials..." -ForegroundColor Cyan
& $AwsExe sts get-caller-identity
if ($LASTEXITCODE -ne 0) {
    throw "AWS credentials test failed."
}

Write-Host ""
Write-Host "AWS configured. Run dev-reset again:" -ForegroundColor Green
Write-Host "  cd stock-backend" -ForegroundColor Green
Write-Host "  .\scripts\dev-reset.ps1" -ForegroundColor Green
