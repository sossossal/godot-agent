param(
    [string]$ApiHost = "127.0.0.1",
    [int]$ApiPort = 8000,
    [string]$ApiBindHost = "127.0.0.1",
    [string]$ReleaseManifestPath = "api_server/static/dist/release_manifest.json",
    [string]$BrowserPath = "",
    [int]$PortalClickScriptTimeoutSeconds = 2700
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportsDir = Join-Path $repoRoot "logs\reports"
$reportPath = Join-Path $reportsDir "full_live_validation.json"
$laneReportsDir = Join-Path $reportsDir "full_live_validation_lanes"
$portalDomSmokeApiPort = 8012
$portalClickSmokeApiPort = 8014
$remoteMcpPort = 8766
New-Item -ItemType Directory -Force -Path $reportsDir | Out-Null
New-Item -ItemType Directory -Force -Path $laneReportsDir | Out-Null

function Convert-ToRepoRelativePath {
    param([string]$PathValue)

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }

    $normalized = $PathValue.Trim()
    if ($normalized.StartsWith("res://")) {
        $normalized = $normalized.Substring(6)
    }

    try {
        if ([System.IO.Path]::IsPathRooted($normalized)) {
            $resolved = [System.IO.Path]::GetFullPath($normalized)
        } else {
            $resolved = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $normalized))
        }
        return [System.IO.Path]::GetRelativePath($repoRoot, $resolved).Replace("\", "/")
    } catch {
        return $normalized.Replace("\", "/")
    }
}

function Resolve-CandidatePath {
    param([string]$RawPath)

    if ([string]::IsNullOrWhiteSpace($RawPath)) {
        return ""
    }

    $normalized = $RawPath.Trim()
    if ($normalized.StartsWith("res://")) {
        $normalized = $normalized.Substring(6)
    }

    if ([System.IO.Path]::IsPathRooted($normalized)) {
        return [System.IO.Path]::GetFullPath($normalized)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $normalized))
}

function Get-ObjectPropertyValue {
    param(
        $InputObject,
        [string]$PropertyName
    )

    if ($null -eq $InputObject -or [string]::IsNullOrWhiteSpace($PropertyName)) {
        return $null
    }

    if ($InputObject -is [System.Collections.IDictionary]) {
        if ($InputObject.Contains($PropertyName)) {
            return $InputObject[$PropertyName]
        }
        return $null
    }

    $property = $InputObject.PSObject.Properties[$PropertyName]
    if ($null -ne $property) {
        return $property.Value
    }

    return $null
}

function Get-ObjectStringProperty {
    param(
        $InputObject,
        [string]$PropertyName
    )

    $value = Get-ObjectPropertyValue -InputObject $InputObject -PropertyName $PropertyName
    if ($null -eq $value) {
        return ""
    }
    return [string]$value
}

function Resolve-ReleaseBinding {
    param([string]$RawManifestPath)

    $candidateSpecs = @()
    if ($RawManifestPath) {
        $candidateSpecs += [ordered]@{
            path = $RawManifestPath
            source = "explicit"
        }
    }
    $candidateSpecs += [ordered]@{
        path = "api_server/static/dist/release_manifest.json"
        source = "stable"
    }

    $distRoot = Join-Path $repoRoot "api_server\static\dist"
    if (Test-Path $distRoot) {
        $versionedManifests = Get-ChildItem -Path $distRoot -Filter "release_manifest.json" -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending
        foreach ($candidate in $versionedManifests) {
            $relativePath = Convert-ToRepoRelativePath -PathValue $candidate.FullName
            if ($relativePath -and $relativePath -ne "api_server/static/dist/release_manifest.json") {
                $candidateSpecs += [ordered]@{
                    path = $candidate.FullName
                    source = "versioned_fallback"
                }
            }
        }
    }

    $seen = @{}
    foreach ($candidateSpec in $candidateSpecs) {
        $resolvedPath = Resolve-CandidatePath -RawPath $candidateSpec.path
        if (-not $resolvedPath) {
            continue
        }

        $candidateKey = $resolvedPath.ToLowerInvariant()
        if ($seen.ContainsKey($candidateKey)) {
            continue
        }
        $seen[$candidateKey] = $true

        if (-not (Test-Path $resolvedPath)) {
            continue
        }

        try {
            $payload = Get-Content -Raw -Path $resolvedPath -Encoding UTF8 | ConvertFrom-Json
        } catch {
            continue
        }

        if ($null -eq $payload) {
            continue
        }

        $buildId = Get-ObjectStringProperty -InputObject $payload -PropertyName "build_id"
        $version = Get-ObjectStringProperty -InputObject $payload -PropertyName "version"
        $channel = Get-ObjectStringProperty -InputObject $payload -PropertyName "channel"

        return [ordered]@{
            status = if ($buildId -and $version -and $channel) { "passed" } else { "warning" }
            manifest_source = [string]$candidateSpec.source
            manifest_path = Convert-ToRepoRelativePath -PathValue $resolvedPath
            build_id = $buildId
            version = $version
            channel = $channel
            generated_at = Get-ObjectStringProperty -InputObject $payload -PropertyName "generated_at"
            release_dir = Convert-ToRepoRelativePath -PathValue (Get-ObjectStringProperty -InputObject $payload -PropertyName "release_dir")
            output_path = Convert-ToRepoRelativePath -PathValue (Get-ObjectStringProperty -InputObject $payload -PropertyName "output_path")
            release_url = Get-ObjectStringProperty -InputObject $payload -PropertyName "release_url"
            versioned_release_url = Get-ObjectStringProperty -InputObject $payload -PropertyName "versioned_release_url"
        }
    }

    $missingManifestPath = "api_server/static/dist/release_manifest.json"
    if (-not [string]::IsNullOrWhiteSpace($RawManifestPath)) {
        $missingManifestPath = $RawManifestPath.Trim().Replace("\", "/")
    }

    return [ordered]@{
        status = "warning"
        manifest_source = "missing"
        manifest_path = $missingManifestPath
        build_id = ""
        version = ""
        channel = ""
        generated_at = ""
        release_dir = ""
        output_path = ""
        release_url = ""
        versioned_release_url = ""
    }
}

function Get-LaneArtifactPaths {
    param(
        [string]$LaneId,
        $StructuredContent
    )

    $candidatePaths = @()
    switch ($LaneId) {
        "godot_live_sandbox" {
            $candidatePaths += @(
                "logs/live_sandbox_state.json",
                "sandbox_project/data_tables/game_creation/input_replay_run.json",
                "sandbox_project/logs/test_artifacts/game_creation/input_replay_tower_defense_2d.gd",
                "sandbox_project/logs/test_artifacts/game_creation/tower_defense_runtime.png",
                ("logs/api_server_{0}.out" -f $ApiPort),
                ("logs/api_server_{0}.err" -f $ApiPort)
            )
        }
        "portal_dom_smoke" {
            $candidatePaths += @(
                ("logs/test_artifacts/portal_browser_smoke_{0}.html" -f $portalDomSmokeApiPort),
                ("logs/test_artifacts/portal_browser_smoke_{0}.err" -f $portalDomSmokeApiPort),
                ("logs/portal_browser_api_{0}.out" -f $portalDomSmokeApiPort),
                ("logs/portal_browser_api_{0}.err" -f $portalDomSmokeApiPort)
            )
        }
        "portal_click_smoke" {
            $candidatePaths += @(
                ("logs/test_artifacts/portal_click_chrome_{0}.out" -f $portalClickSmokeApiPort),
                ("logs/test_artifacts/portal_click_chrome_{0}.err" -f $portalClickSmokeApiPort),
                ("logs/portal_click_api_{0}.out" -f $portalClickSmokeApiPort),
                ("logs/portal_click_api_{0}.err" -f $portalClickSmokeApiPort)
            )
        }
        "remote_mcp_live" {
            $candidatePaths += @(
                ("logs/remote_mcp_{0}.out" -f $remoteMcpPort),
                ("logs/remote_mcp_{0}.err" -f $remoteMcpPort)
            )
        }
    }

    if ($StructuredContent) {
        foreach ($fieldName in @(
            "dom_path",
            "api_stdout",
            "api_stderr",
            "chrome_stdout",
            "chrome_stderr",
            "out_path",
            "err_path",
            "state_path",
            "report_path",
            "manifest_path"
        )) {
            $fieldValue = Get-ObjectStringProperty -InputObject $StructuredContent -PropertyName $fieldName
            if (-not [string]::IsNullOrWhiteSpace($fieldValue)) {
                $candidatePaths += $fieldValue
            }
        }
    }

    $artifactPaths = @()
    $seen = @{}
    foreach ($candidate in $candidatePaths) {
        $relativePath = Convert-ToRepoRelativePath -PathValue ([string]$candidate)
        if (-not $relativePath) {
            continue
        }
        $artifactKey = $relativePath.ToLowerInvariant()
        if ($seen.ContainsKey($artifactKey)) {
            continue
        }
        $seen[$artifactKey] = $true
        $artifactPaths += $relativePath
    }

    return $artifactPaths
}

function Get-StructuredFlowStatuses {
    param(
        $StructuredContent
    )

    if (-not $StructuredContent -or -not $StructuredContent.result) {
        return [ordered]@{}
    }

    $flowStatuses = [ordered]@{}
    foreach ($property in $StructuredContent.result.PSObject.Properties) {
        $name = [string]$property.Name
        if ([string]::IsNullOrWhiteSpace($name)) {
            continue
        }
        if ($name -ne "flow" -and -not $name.EndsWith("_flow")) {
            continue
        }
        $normalized = [string]$property.Value
        if ([string]::IsNullOrWhiteSpace($normalized)) {
            continue
        }
        $normalized = $normalized.Trim().ToLowerInvariant()
        if (@("passed", "warning", "blocked", "skipped") -contains $normalized) {
            $flowStatuses[$name] = $normalized
        }
    }

    return $flowStatuses
}

function Write-LiveValidationLaneReport {
    param(
        [string]$LaneId,
        [string]$Label,
        [string]$Status,
        [string]$Summary,
        $ArtifactPaths,
        $Details
    )

    $laneReportRelativePath = ("logs/reports/full_live_validation_lanes/{0}.json" -f $LaneId)
    $laneReportAbsolutePath = Join-Path $laneReportsDir ("{0}.json" -f $LaneId)
    $payload = [ordered]@{
        schema_version = "1.0"
        lane_id = $LaneId
        label = $Label
        status = $Status
        summary = $Summary
        executed_at = $executedAt
        report_path = $laneReportRelativePath
        full_report_path = "logs/reports/full_live_validation.json"
        artifact_paths = @($ArtifactPaths)
        release_binding = $releaseBinding
        details = $Details
    }
    Set-Content -LiteralPath $laneReportAbsolutePath -Value ($payload | ConvertTo-Json -Depth 14) -Encoding UTF8
    return $laneReportRelativePath
}

function Invoke-LiveValidationStep {
    param(
        [string]$Id,
        [string]$Label,
        [string]$Command,
        [string]$Summary,
        [scriptblock]$Action
    )

    Write-Host $Label
    $capturedOutput = @()
    $exitCode = 0
    $status = "passed"
    $message = $Summary
    $structuredContent = $null

    try {
        # Reset stale external-process exit codes so one failed lane does not poison the next PowerShell step.
        $global:LASTEXITCODE = $null
        $capturedOutput = @(& $Action *>&1)
        if ($null -ne $LASTEXITCODE) {
            $exitCode = [int]$LASTEXITCODE
        }
        if ($exitCode -ne 0) {
            throw "command exited with code $exitCode"
        }
    } catch {
        if ($exitCode -eq 0) {
            if ($null -ne $LASTEXITCODE -and [int]$LASTEXITCODE -ne 0) {
                $exitCode = [int]$LASTEXITCODE
            } else {
                $exitCode = 1
            }
        }
        $status = "blocked"
        $message = $_.Exception.Message
    }

    $outputLines = @($capturedOutput | ForEach-Object { $_.ToString() })
    $joinedOutput = ($outputLines -join [Environment]::NewLine).Trim()
    if ($joinedOutput.StartsWith("{") -and $joinedOutput.EndsWith("}")) {
        try {
            $structuredContent = ($joinedOutput | ConvertFrom-Json)
        } catch {
        }
    }

    $artifactPaths = Get-LaneArtifactPaths -LaneId $Id -StructuredContent $structuredContent
    $details = [ordered]@{
        exit_code = $exitCode
        output_line_count = $outputLines.Count
        artifact_paths = $artifactPaths
    }

    if ($structuredContent) {
        $details["structured_content"] = $structuredContent
        $flowStatuses = Get-StructuredFlowStatuses -StructuredContent $structuredContent
        if ($flowStatuses.Count -gt 0) {
            $details["flow_statuses"] = $flowStatuses
        }
    }

    if ($Id -eq "godot_live_sandbox") {
        $details["expected_live_tests"] = @(
            "tests/test_live_sandbox.py::test_8_p19_scene_graph_snapshot_reaches_health_monitor",
            "tests/test_live_sandbox.py::test_9_p19_runtime_playability_smoke_generated_tower_defense",
            "tests/test_live_sandbox.py::test_10_p19_execute_replay_generates_runtime_screenshot"
        )
        $details["p19_replay_evidence"] = [ordered]@{
            replay_report_path = "sandbox_project/data_tables/game_creation/input_replay_run.json"
            replay_script_path = "sandbox_project/logs/test_artifacts/game_creation/input_replay_tower_defense_2d.gd"
            runtime_screenshot_path = "sandbox_project/logs/test_artifacts/game_creation/tower_defense_runtime.png"
            live_test = "tests/test_live_sandbox.py::test_10_p19_execute_replay_generates_runtime_screenshot"
        }
        if (-not $details.Contains("flow_statuses")) {
            $details["flow_statuses"] = [ordered]@{}
        }
        $details["flow_statuses"]["p19_execute_replay_flow"] = $status
    }

    if ($outputLines.Count -gt 0) {
        $details["last_output_line"] = $outputLines[-1]
    }
    $laneReportPath = Write-LiveValidationLaneReport `
        -LaneId $Id `
        -Label $Label `
        -Status $status `
        -Summary $message `
        -ArtifactPaths $artifactPaths `
        -Details $details
    $details["report_path"] = $laneReportPath

    return [ordered]@{
        id = $Id
        label = $Label
        status = $status
        command = $Command
        summary = $message
        report_path = $laneReportPath
        artifact_paths = $artifactPaths
        details = $details
    }
}

$releaseBinding = Resolve-ReleaseBinding -RawManifestPath $ReleaseManifestPath
$executedAt = [DateTime]::UtcNow.ToString("o")
$portalDomSmokeCommand = ".\tools\run_portal_browser_smoke.ps1"
$portalClickSmokeCommand = "python .\tools\run_portal_browser_click_smoke.py --release-manifest-path $ReleaseManifestPath --script-timeout $PortalClickScriptTimeoutSeconds"
if (-not [string]::IsNullOrWhiteSpace($BrowserPath)) {
    $portalDomSmokeCommand += " -BrowserPath $BrowserPath"
    $portalClickSmokeCommand += " --browser-path $BrowserPath"
}
$steps = @(
    (Invoke-LiveValidationStep `
        -Id "godot_live_sandbox" `
        -Label "Godot live sandbox and production flow checks" `
        -Command ".\tools\run_live_sandbox_tests.ps1 -ApiHost $ApiHost -ApiPort $ApiPort -ApiBindHost $ApiBindHost -PytestArgs tests/test_live_sandbox.py tests/test_live_production_flows.py -v -s" `
        -Summary "tests/test_live_sandbox.py + tests/test_live_production_flows.py passed" `
        -Action {
            .\tools\run_live_sandbox_tests.ps1 `
                -ApiHost $ApiHost `
                -ApiPort $ApiPort `
                -ApiBindHost $ApiBindHost `
                -PytestArgs @(
                    "tests/test_live_sandbox.py",
                    "tests/test_live_production_flows.py",
                    "-v",
                    "-s"
                )
        }),
    (Invoke-LiveValidationStep `
        -Id "portal_dom_smoke" `
        -Label "Portal browser DOM smoke" `
        -Command $portalDomSmokeCommand `
        -Summary "Portal DOM smoke passed" `
        -Action {
            if ([string]::IsNullOrWhiteSpace($BrowserPath)) {
                .\tools\run_portal_browser_smoke.ps1
            } else {
                .\tools\run_portal_browser_smoke.ps1 -BrowserPath $BrowserPath
            }
        }),
    (Invoke-LiveValidationStep `
        -Id "portal_click_smoke" `
        -Label "Portal browser click smoke" `
        -Command $portalClickSmokeCommand `
        -Summary "Portal click smoke passed" `
        -Action {
            $portalClickArgs = @(
                ".\tools\run_portal_browser_click_smoke.py",
                "--release-manifest-path", $ReleaseManifestPath,
                "--script-timeout", [string]$PortalClickScriptTimeoutSeconds
            )
            if (-not [string]::IsNullOrWhiteSpace($BrowserPath)) {
                $portalClickArgs += @("--browser-path", $BrowserPath)
            }
            python @portalClickArgs
        }),
    (Invoke-LiveValidationStep `
        -Id "remote_mcp_live" `
        -Label "Remote MCP live smoke" `
        -Command ".\tools\run_remote_mcp_live_smoke.ps1" `
        -Summary "Remote MCP live smoke passed" `
        -Action {
            .\tools\run_remote_mcp_live_smoke.ps1
        })
)

$blockingIssues = @()
foreach ($step in $steps) {
    if ($step.status -eq "blocked") {
        $blockingIssues += [ordered]@{
            code = "lane_failed_$($step.id)"
            lane_id = $step.id
            message = $step.summary
            artifact_paths = @($step.artifact_paths)
        }
    }
}

$payload = [ordered]@{
    schema_version = "1.1"
    ok = ($blockingIssues.Count -eq 0)
    executed_at = $executedAt
    api_host = $ApiHost
    api_port = $ApiPort
    report_path = "logs/reports/full_live_validation.json"
    release_binding = $releaseBinding
    lane_count = $steps.Count
    passed_lane_count = @($steps | Where-Object { $_.status -eq "passed" }).Count
    warning_lane_count = @($steps | Where-Object { $_.status -eq "warning" }).Count
    blocked_lane_count = @($steps | Where-Object { $_.status -eq "blocked" }).Count
    steps = $steps
    blocking_issues = $blockingIssues
}

$payloadJson = $payload | ConvertTo-Json -Depth 14
Set-Content -LiteralPath $reportPath -Value $payloadJson -Encoding UTF8
$payloadJson

if ($blockingIssues.Count -gt 0) {
    throw "Full live validation failed: $($blockingIssues[0].code)"
}
