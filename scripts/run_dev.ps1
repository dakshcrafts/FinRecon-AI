# Run Gripher in local development mode
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   GRIPHER - Starting Development Shell   " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python.exe"
}

Write-Host "Using Python: $pythonExe" -ForegroundColor Green
& $pythonExe desktop_run.py

