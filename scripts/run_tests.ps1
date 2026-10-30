# Run full test suite for Gripher
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   GRIPHER - Running Automated Tests      " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$pytestExe = Join-Path $projectRoot ".venv\Scripts\pytest.exe"
if (-not (Test-Path $pytestExe)) {
    $pytestExe = "pytest.exe"
}

& $pytestExe -v tests
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nAll tests passed successfully!" -ForegroundColor Green
} else {
    Write-Host "`nTests encountered failures (Exit code: $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}
