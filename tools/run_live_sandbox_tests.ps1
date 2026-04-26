[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$ProjectPath,
    [string]$ApiHost,
    [int]$ApiPort,
    [string]$ApiBindHost,
    [int]$ServerStartupTimeout = 20,
    [int]$EditorTimeout = 45,
    [string[]]$PytestArgs = @("tests/test_live_sandbox.py", "-v", "-s")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

$startScript = Join-Path $PSScriptRoot "start_live_sandbox.ps1"
$stopScript = Join-Path $PSScriptRoot "stop_live_sandbox.ps1"
$pythonExe = (Get-Command python -ErrorAction Stop).Source

if (-not (Test-Path $startScript)) {
    throw "Missing script: $startScript"
}

if (-not (Test-Path $stopScript)) {
    throw "Missing script: $stopScript"
}

$startParams = @{
    RepoRoot = $RepoRoot
    ServerStartupTimeout = $ServerStartupTimeout
    EditorTimeout = $EditorTimeout
}

if ($ProjectPath) {
    $startParams.ProjectPath = $ProjectPath
}

if ($ApiHost) {
    $startParams.ApiHost = $ApiHost
}

if ($ApiPort -gt 0) {
    $startParams.ApiPort = $ApiPort
}

if ($ApiBindHost) {
    $startParams.ApiBindHost = $ApiBindHost
}

$stopParams = @{
    RepoRoot = $RepoRoot
}

if ($ApiPort -gt 0) {
    $stopParams.ApiPort = $ApiPort
}

$pytestExitCode = 1

try {
    & $startScript @startParams | Out-Host

    if ($ApiHost) {
        $env:GODOT_AGENT_API_HOST = $ApiHost
    }

    if ($ApiPort -gt 0) {
        $env:GODOT_AGENT_API_PORT = [string]$ApiPort
    }

    if ($ApiBindHost) {
        $env:GODOT_AGENT_API_BIND_HOST = $ApiBindHost
    }

    & $pythonExe -m pytest @PytestArgs
    $pytestExitCode = $LASTEXITCODE
} finally {
    & $stopScript @stopParams | Out-Host
}

exit $pytestExitCode
