# Verify the built Gripher executable
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot

$exePath = Join-Path $projectRoot "dist\Gripher\Gripher.exe"

Write-Host "Verifying executable at: $exePath" -ForegroundColor Cyan
if (-not (Test-Path $exePath)) {
    Write-Host "Error: Executable does not exist at $exePath" -ForegroundColor Red
    exit 1
}

$fileItem = Get-Item $exePath
Write-Host "File exists. Size: $([math]::Round($fileItem.Length / 1MB, 2)) MB" -ForegroundColor Green

# Verify bundled resources
$templatesDir = Join-Path $projectRoot "dist\Gripher\_internal\app\templates"
if (-not (Test-Path $templatesDir)) {
    $templatesDir = Join-Path $projectRoot "dist\Gripher\app\templates"
}

if (Test-Path $templatesDir) {
    Write-Host "Templates bundle verified at $templatesDir" -ForegroundColor Green
} else {
    Write-Host "Warning: templates directory path should be verified" -ForegroundColor Yellow
}

Write-Host "`nGripher.exe verification passed!" -ForegroundColor Green

