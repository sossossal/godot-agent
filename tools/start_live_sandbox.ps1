[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$ProjectPath,
    [string]$ApiHost,
    [int]$ApiPort,
    [string]$ApiBindHost,
    [int]$ServerStartupTimeout = 20,
    [int]$EditorTimeout = 45
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Use-DefaultString {
    param(
        [string]$Value,
        [string]$Default
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $Default
    }
    return $Value.Trim()
}

function Use-DefaultInt {
    param(
        [int]$Value,
        [string]$EnvName,
        [int]$Default
    )

    if ($Value -gt 0) {
        return $Value
    }

    $raw = [Environment]::GetEnvironmentVariable($EnvName)
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $Default
    }

    $parsed = 0
    if ([int]::TryParse($raw.Trim(), [ref]$parsed)) {
        return $parsed
    }

    return $Default
}

function Stop-PortProcess {
    param([int]$Port)

    try {
        $owners = Get-NetTCPConnection -LocalPort $Port -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($owner in $owners) {
            if ($owner) {
                Stop-Process -Id $owner -Force -ErrorAction Stop
            }
        }
    } catch {
    }
}

function Wait-HttpReady {
    param(
        [string]$Uri,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds([Math]::Max(3, $TimeoutSeconds))
    while ((Get-Date) -lt $deadline) {
        try {
            return Invoke-RestMethod -Method Get -Uri $Uri -TimeoutSec 3
        } catch {
            Start-Sleep -Seconds 1
        }
    }

    throw "API server did not become ready at $Uri within $TimeoutSeconds seconds."
}

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

if (-not $ProjectPath) {
    $ProjectPath = Join-Path $RepoRoot "sandbox_project"
}
$ProjectPath = (Resolve-Path $ProjectPath).Path

$ApiHost = Use-DefaultString -Value $ApiHost -Default (Use-DefaultString -Value ([Environment]::GetEnvironmentVariable("GODOT_AGENT_API_HOST")) -Default "127.0.0.1")
$ApiBindHost = Use-DefaultString -Value $ApiBindHost -Default (Use-DefaultString -Value ([Environment]::GetEnvironmentVariable("GODOT_AGENT_API_BIND_HOST")) -Default "127.0.0.1")
$ApiPort = Use-DefaultInt -Value $ApiPort -EnvName "GODOT_AGENT_API_PORT" -Default 8000

$PluginSrc = Join-Path $RepoRoot "addons\godot_agent"
$PluginDst = Join-Path $ProjectPath "addons\godot_agent"
$LogsDir = Join-Path $RepoRoot "logs"
$StatePath = Join-Path $LogsDir "live_sandbox_state.json"

if (-not (Test-Path $PluginSrc)) {
    throw "Plugin source not found: $PluginSrc"
}

if (-not (Test-Path $ProjectPath)) {
    throw "Sandbox project not found: $ProjectPath"
}

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
New-Item -ItemType Directory -Force -Path $PluginDst | Out-Null
Copy-Item -Path (Join-Path $PluginSrc "*") -Destination $PluginDst -Recurse -Force

$env:GODOT_AGENT_API_HOST = $ApiHost
$env:GODOT_AGENT_API_PORT = [string]$ApiPort
$env:GODOT_AGENT_API_BIND_HOST = $ApiBindHost

$BaseUrl = "http://{0}:{1}" -f $ApiHost, $ApiPort
$ApiOut = Join-Path $LogsDir ("api_server_{0}.out" -f $ApiPort)
$ApiErr = Join-Path $LogsDir ("api_server_{0}.err" -f $ApiPort)
$PythonExe = (Get-Command python -ErrorAction Stop).Source

Remove-Item -Path $ApiOut, $ApiErr -Force -ErrorAction SilentlyContinue
Stop-PortProcess -Port $ApiPort

$ApiProcess = $null

try {
    $ApiProcess = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @("-m", "api_server.main") `
        -WorkingDirectory $RepoRoot `
        -PassThru `
        -RedirectStandardOutput $ApiOut `
        -RedirectStandardError $ApiErr

    Wait-HttpReady -Uri ("{0}/health" -f $BaseUrl) -TimeoutSeconds $ServerStartupTimeout | Out-Null

    $LaunchBody = @{
        project_path = $ProjectPath
        wait_for_editor = $true
        editor_timeout = $EditorTimeout
    } | ConvertTo-Json
    $LaunchBytes = [System.Text.Encoding]::UTF8.GetBytes($LaunchBody)

    $LaunchResponse = Invoke-RestMethod `
        -Method Post `
        -Uri ("{0}/editor/launch" -f $BaseUrl) `
        -ContentType "application/json; charset=utf-8" `
        -Body $LaunchBytes `
        -TimeoutSec ($EditorTimeout + 10)

    if (-not $LaunchResponse.editor_online) {
        throw "Godot editor did not come online."
    }

    $State = [ordered]@{
        ok = $true
        api_pid = $ApiProcess.Id
        godot_pid = $LaunchResponse.launch.pid
        api_host = $ApiHost
        api_port = $ApiPort
        api_bind_host = $ApiBindHost
        base_url = $BaseUrl
        project_path = $ProjectPath
        api_stdout = $ApiOut
        api_stderr = $ApiErr
        launch = $LaunchResponse.launch
        editor_state = $LaunchResponse.editor_state
        started_at = (Get-Date).ToString("o")
    }

    $State | ConvertTo-Json -Depth 10 | Set-Content -Path $StatePath -Encoding utf8
    $State | ConvertTo-Json -Depth 10
} catch {
    if ($ApiProcess -and -not $ApiProcess.HasExited) {
        Stop-Process -Id $ApiProcess.Id -Force -ErrorAction SilentlyContinue
    }
    throw
}
