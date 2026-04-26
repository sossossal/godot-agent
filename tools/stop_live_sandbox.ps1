[CmdletBinding()]
param(
    [string]$RepoRoot,
    [int]$ApiPort
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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

function Stop-ProcessIfRunning {
    param([Nullable[int]]$ProcessId)

    if (-not $ProcessId) {
        return $false
    }

    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        Stop-Process -Id $process.Id -Force -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
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

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

$ApiPort = Use-DefaultInt -Value $ApiPort -EnvName "GODOT_AGENT_API_PORT" -Default 8000
$LogsDir = Join-Path $RepoRoot "logs"
$StatePath = Join-Path $LogsDir "live_sandbox_state.json"
$Stopped = @()

if (Test-Path $StatePath) {
    $State = Get-Content -Path $StatePath -Raw | ConvertFrom-Json

    if (Stop-ProcessIfRunning -ProcessId $State.api_pid) {
        $Stopped += "api:$($State.api_pid)"
    }

    if (Stop-ProcessIfRunning -ProcessId $State.godot_pid) {
        $Stopped += "godot:$($State.godot_pid)"
    }

    Remove-Item -Path $StatePath -Force
}

Stop-PortProcess -Port $ApiPort

[ordered]@{
    ok = $true
    api_port = $ApiPort
    stopped = $Stopped
} | ConvertTo-Json -Depth 4
