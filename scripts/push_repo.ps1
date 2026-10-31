param (
    [string]$Token = $env:GITHUB_TOKEN
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectDir = Split-Path -Parent $ScriptDir
$PythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

if ($Token) {
    & $PythonExe (Join-Path $ScriptDir "push_repo.py") $Token
} else {
    & $PythonExe (Join-Path $ScriptDir "push_repo.py")
}
