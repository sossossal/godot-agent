param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8766,
    [int]$StartupTimeout = 30,
    [int]$ToolTimeoutSec = 120
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logsDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

$outPath = Join-Path $logsDir "remote_mcp_$Port.out"
$errPath = Join-Path $logsDir "remote_mcp_$Port.err"
Remove-Item -Force $outPath,$errPath -ErrorAction SilentlyContinue

$remoteProc = $null
$currentStep = "startup"
try {
    $currentStep = "start_server"
    $remoteProc = Start-Process -FilePath python `
        -ArgumentList @("-m", "uvicorn", "bridge.remote_mcp_server:app", "--host", $HostName, "--port", [string]$Port) `
        -WorkingDirectory $repoRoot `
        -PassThru `
        -RedirectStandardOutput $outPath `
        -RedirectStandardError $errPath

    $baseUrl = "http://$HostName`:$Port"
    $deadline = (Get-Date).AddSeconds($StartupTimeout)
    $health = $null
    $currentStep = "wait_health"
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Method Get -Uri "$baseUrl/health" -TimeoutSec 2
            break
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $health) {
        throw "Remote MCP bridge did not become healthy at $baseUrl/health"
    }

    $currentStep = "fetch_manifest"
    $manifest = Invoke-RestMethod -Method Get -Uri "$baseUrl/mcp/manifest" -TimeoutSec 5

    $productionBody = @{
        arguments = @{
            project_path = $repoRoot
            scenario_id = "vertical_slice_2d"
            evidence = @{
                contract = $true
                tests = $true
                docs = $true
                quality_dashboard = $true
            }
            changed_paths = @("scenes/Main.tscn", "scripts/player_controller.gd", "README.md")
            mode = "strict"
        }
    } | ConvertTo-Json -Depth 10
    $currentStep = "godot_production_validate"
    $production = Invoke-RestMethod `
        -Method Post `
        -Uri "$baseUrl/tools/godot_production_validate" `
        -ContentType "application/json; charset=utf-8" `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($productionBody)) `
        -TimeoutSec $ToolTimeoutSec

    if ($production.is_error) {
        throw "godot_production_validate returned is_error=true"
    }
    if ($production.structured_content.readiness_status -ne "passed") {
        throw "godot_production_validate did not pass: $($production.structured_content.message)"
    }

    $compatBody = @{
        arguments = @{
            project_path = $repoRoot
            providers = @("codex", "openai_api")
        }
    } | ConvertTo-Json -Depth 10
    $currentStep = "godot_agent_compat"
    $compat = Invoke-RestMethod `
        -Method Post `
        -Uri "$baseUrl/tools/godot_agent_compat" `
        -ContentType "application/json; charset=utf-8" `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($compatBody)) `
        -TimeoutSec $ToolTimeoutSec

    if ($compat.is_error) {
        throw "godot_agent_compat returned is_error=true"
    }
    if (-not $compat.structured_content.passed) {
        throw "godot_agent_compat did not pass: $($compat.structured_content.status)"
    }

    [pscustomobject]@{
        ok = $true
        base_url = $baseUrl
        pid = $remoteProc.Id
        tool_count = $manifest.tools.Count
        tool_timeout_sec = $ToolTimeoutSec
        production_status = $production.structured_content.readiness_status
        production_blocking_checks = $production.structured_content.blocking_checks
        agent_compat_status = $compat.structured_content.status
        agent_compat_provider_count = $compat.structured_content.provider_count
    } | ConvertTo-Json -Depth 8
} catch {
    throw "Remote MCP live smoke failed at step=${currentStep}: $($_.Exception.Message)"
} finally {
    if ($remoteProc -and -not $remoteProc.HasExited) {
        Stop-Process -Id $remoteProc.Id -Force
    }
}
