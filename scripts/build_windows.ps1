# Build Windows Executable for Gripher using PyInstaller
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   GRIPHER - Building Windows Executable  " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$pyinstallerExe = Join-Path $projectRoot ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $pyinstallerExe)) {
    $pyinstallerExe = "pyinstaller.exe"
}

$specFile = Join-Path $projectRoot "packaging\gripher.spec"

Write-Host "Building Gripher with spec: $specFile" -ForegroundColor Yellow
& $pyinstallerExe --clean --noconfirm $specFile

$outputExe = Join-Path $projectRoot "dist\Gripher\Gripher.exe"
if (Test-Path $outputExe) {
    Write-Host "`nBuild successful!" -ForegroundColor Green
    Write-Host "Standalone executable location: $outputExe" -ForegroundColor Cyan
} else {
    Write-Host "`nBuild failed: $outputExe not found." -ForegroundColor Red
    exit 1
}
