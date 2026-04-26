param(
    [string]$ApiHost = "127.0.0.1",
    [int]$ApiPort = 8012,
    [string]$BrowserPath = "",
    [int]$ServerStartupTimeout = 20
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logsDir = Join-Path $repoRoot "logs"
$artifactDir = Join-Path $repoRoot "logs\test_artifacts"
$browserProfileRoot = Join-Path $logsDir "browser_profiles"
New-Item -ItemType Directory -Force -Path $logsDir,$artifactDir,$browserProfileRoot | Out-Null

function Resolve-BrowserPath {
    param([string]$RequestedPath)

    $candidates = @()
    if ($RequestedPath) {
        $candidates += $RequestedPath
    }
    $candidates += @(
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }

    foreach ($commandName in @("chrome", "msedge", "chromium", "chromium-browser")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command -and $command.Source) {
            return $command.Source
        }
    }

    return ""
}

$browser = Resolve-BrowserPath -RequestedPath $BrowserPath
if (-not $browser) {
    throw "No Chromium-compatible browser found. Install Microsoft Edge or Chrome, or pass -BrowserPath."
}

$apiOut = Join-Path $logsDir "portal_browser_api_$ApiPort.out"
$apiErr = Join-Path $logsDir "portal_browser_api_$ApiPort.err"
$domPath = Join-Path $artifactDir "portal_browser_smoke_$ApiPort.html"
$browserErr = Join-Path $artifactDir "portal_browser_smoke_$ApiPort.err"
$userDataDir = Join-Path $browserProfileRoot ("portal_browser_profile_{0}_{1}" -f $ApiPort, [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())
Remove-Item -Force $apiOut,$apiErr,$domPath,$browserErr -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $userDataDir | Out-Null

$env:GODOT_AGENT_API_HOST = $ApiHost
$env:GODOT_AGENT_API_PORT = [string]$ApiPort
$env:GODOT_AGENT_API_BIND_HOST = $ApiHost

$apiProc = $null
try {
    $apiProc = Start-Process -FilePath python `
        -ArgumentList @("-m", "api_server.main") `
        -WorkingDirectory $repoRoot `
        -PassThru `
        -RedirectStandardOutput $apiOut `
        -RedirectStandardError $apiErr

    $healthUrl = "http://$ApiHost`:$ApiPort/health"
    $deadline = (Get-Date).AddSeconds($ServerStartupTimeout)
    $health = $null
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Method Get -Uri $healthUrl -TimeoutSec 2
            break
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $health) {
        throw "API server did not become healthy at $healthUrl"
    }

    $scenarioPayload = Invoke-RestMethod -Method Get -Uri "http://$ApiHost`:$ApiPort/production/scenarios?project_path=default" -TimeoutSec 5
    $compatPayload = Invoke-RestMethod -Method Get -Uri "http://$ApiHost`:$ApiPort/agent-compat/providers?project_path=default" -TimeoutSec 5

    $portalUrl = "http://$ApiHost`:$ApiPort/portal/index.html"
    $browserArgs = @(
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-crash-reporter",
        "--disable-breakpad",
        "--disable-crashpad",
        "--no-first-run",
        "--user-data-dir=$userDataDir",
        "--dump-dom",
        $portalUrl
    )

    $browserProc = Start-Process -FilePath $browser `
        -ArgumentList $browserArgs `
        -Wait `
        -PassThru `
        -RedirectStandardOutput $domPath `
        -RedirectStandardError $browserErr
    $browserExitCode = if ($null -eq $browserProc.ExitCode) { 0 } else { [int]$browserProc.ExitCode }
    if ($browserExitCode -ne 0) {
        throw "Browser smoke failed with exit code $browserExitCode. See $browserErr"
    }
    if (-not (Test-Path $domPath) -or (Get-Item $domPath).Length -eq 0) {
        throw "Browser smoke did not capture Portal DOM. See $browserErr"
    }

    $dom = Get-Content -Raw -Path $domPath -Encoding UTF8
    # Keep the DOM smoke markers ASCII-only so the script stays parseable in Windows PowerShell without a BOM.
    $requiredMarkers = @(
        'id="onboarding-meta"',
        'id="quality-meta"',
        'id="governance-meta"',
        'id="production-meta"',
        'id="release-candidate-meta"',
        'id="build-run-matrix-meta"',
        'id="agent-compat-meta"',
        'id="release-promotion-meta"',
        'id="release-execution-meta"',
        'id="art-asset-meta"',
        'id="outsource-gate-meta"',
        'id="asset-review-meta"',
        'id="scene-ownership-meta"',
        'id="presentation-meta"',
        'id="liveops-meta"',
        'id="telemetry-meta"',
        'id="performance-meta"',
        'id="platform-delivery-meta"'
    )
    $missingMarkers = @($requiredMarkers | Where-Object { $dom -notlike "*$_*" })
    if ($missingMarkers.Count -gt 0) {
        throw "Portal DOM is missing expected markers: $($missingMarkers -join ', ')"
    }

    [pscustomobject]@{
        ok = $true
        browser = $browser
        portal_url = $portalUrl
        dom_path = $domPath
        api_pid = $apiProc.Id
        scenario_count = $scenarioPayload.scenario_count
        provider_count = $compatPayload.provider_count
        required_markers = $requiredMarkers
    } | ConvertTo-Json -Depth 6
} finally {
    if ($apiProc -and -not $apiProc.HasExited) {
        Stop-Process -Id $apiProc.Id -Force
    }
}
