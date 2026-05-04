param(
    [string]$PythonCommand = "",
    [string]$PythonPath = "",
    [ValidateSet("all", "quick", "release", "customer")]
    [string]$Profile = "all",
    [string]$Shard = "",
    [string]$ReportPath = "logs/reports/non_live_validation_shards.json",
    [string]$MarkdownPath = "logs/reports/non_live_validation_shards.md",
    [int]$ShardTimeoutSeconds = 1200,
    [int]$SlowShardSeconds = 180,
    [switch]$FailOnSlowShards,
    [switch]$ContinueOnFailure,
    [switch]$Preview
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

function Resolve-PythonCommand {
    if (-not [string]::IsNullOrWhiteSpace($PythonCommand)) {
        return $PythonCommand
    }
    if (-not [string]::IsNullOrWhiteSpace($env:PYTHON)) {
        return $env:PYTHON
    }
    return "python"
}

function New-Shard {
    param(
        [string]$Id,
        [string]$Label,
        [string[]]$PytestArgs
    )
    return [ordered]@{
        id = $Id
        label = $Label
        pytest_args = @($PytestArgs)
    }
}

function ConvertTo-ProcessArgument {
    param([string]$Value)
    $text = [string]$Value
    if ($text -notmatch '[\s"]') {
        return $text
    }
    return '"' + ($text -replace '"', '\"') + '"'
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedReportPath = if ([System.IO.Path]::IsPathRooted($ReportPath)) {
    [System.IO.Path]::GetFullPath($ReportPath)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $ReportPath))
}
$resolvedMarkdownPath = if ([System.IO.Path]::IsPathRooted($MarkdownPath)) {
    [System.IO.Path]::GetFullPath($MarkdownPath)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $MarkdownPath))
}
$resolvedPython = Resolve-PythonCommand

$commonArgs = @("-q", "--color=no", "--durations=10")
$defaultPythonPathEntries = @($repoRoot)
$venvSitePackages = Join-Path $repoRoot ".venv\Lib\site-packages"
if (Test-Path $venvSitePackages) {
    $defaultPythonPathEntries += @(
        $venvSitePackages,
        (Join-Path $venvSitePackages "win32"),
        (Join-Path $venvSitePackages "win32\lib"),
        (Join-Path $venvSitePackages "Pythonwin")
    )
}
$resolvedPythonPath = if (-not [string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath
} else {
    ($defaultPythonPathEntries -join [System.IO.Path]::PathSeparator)
}

function Write-NonLiveValidationReport {
    param(
        [object[]]$Results,
        [bool]$OverallOk,
        [string]$StartedAt,
        [string]$ReportState
    )

    $completedIds = @($Results | ForEach-Object { $_.id })
    $pendingShardIds = @($shards | Where-Object { $completedIds -notcontains $_.id } | ForEach-Object { $_.id })
    $totalDurationSeconds = [Math]::Round((@($Results) | Measure-Object -Property duration_seconds -Sum).Sum, 2)
    $passedCount = @($Results | Where-Object { $_.status -eq "passed" }).Count
    $blockedCount = @($Results | Where-Object { $_.status -eq "blocked" }).Count
    $timeoutCount = @($Results | Where-Object { $_.status -eq "timeout" }).Count
    $statusCounts = [ordered]@{
        passed = $passedCount
        blocked = $blockedCount
        timeout = $timeoutCount
    }
    $slowShards = @(
        $Results |
            Where-Object { [double]$_.duration_seconds -ge [double]$SlowShardSeconds } |
            Sort-Object -Property duration_seconds -Descending |
            ForEach-Object {
                [ordered]@{
                    id = $_.id
                    label = $_.label
                    duration_seconds = $_.duration_seconds
                    status = $_.status
                }
            }
    )
    $effectiveOk = $OverallOk
    if ($FailOnSlowShards -and $slowShards.Count -gt 0) {
        $effectiveOk = $false
    }
    if ($ReportState -ne "complete") {
        $effectiveOk = $false
    }

    $payload = [ordered]@{
        schema_version = "1.0"
        ok = $effectiveOk
        status = if ($ReportState -ne "complete") { "running" } elseif ($effectiveOk) { "passed" } else { "blocked" }
        report_state = $ReportState
        profile = $Profile
        started_at = $StartedAt
        finished_at = (Get-Date).ToUniversalTime().ToString("o")
        python_command = $resolvedPython
        python_path = $env:PYTHONPATH
        planned_shard_count = @($shards).Count
        completed_shard_count = @($Results).Count
        pending_shard_count = @($pendingShardIds).Count
        pending_shards = $pendingShardIds
        shard_count = @($Results).Count
        passed_count = $passedCount
        blocked_count = $blockedCount
        timeout_count = $timeoutCount
        status_counts = $statusCounts
        total_duration_seconds = $totalDurationSeconds
        slow_shard_threshold_seconds = $SlowShardSeconds
        fail_on_slow_shards = [bool]$FailOnSlowShards
        slow_shard_gate = if ($FailOnSlowShards -and $slowShards.Count -gt 0) { "blocked" } elseif ($slowShards.Count -gt 0) { "warning" } else { "passed" }
        slow_shards = $slowShards
        recommended_followup_shards = @($slowShards | ForEach-Object { $_.id })
        failed_shards = @($Results | Where-Object { $_.status -ne "passed" } | ForEach-Object { $_.id })
        results = $Results
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resolvedReportPath) | Out-Null
    $payload | ConvertTo-Json -Depth 8 | Set-Content -Path $resolvedReportPath -Encoding utf8

    $lines = @(
        "# Non-Live Validation Shards",
        "",
        "- Status: $($payload.status)",
        "- Report state: $($payload.report_state)",
        "- Profile: $($payload.profile)",
        "- Planned shards: $($payload.planned_shard_count)",
        "- Completed shards: $($payload.completed_shard_count)",
        "- Pending shards: $($payload.pending_shard_count)",
        "- Pending shard ids: $((@($payload.pending_shards) -join ', '))",
        "- Shards: $($payload.shard_count)",
        "- Passed count: $($payload.passed_count)",
        "- Blocked count: $($payload.blocked_count)",
        "- Timeout count: $($payload.timeout_count)",
        "- Total seconds: $($payload.total_duration_seconds)",
        "- Slow threshold seconds: $($payload.slow_shard_threshold_seconds)",
        "- Slow shard gate: $($payload.slow_shard_gate)",
        "- Slow shards: $((@($payload.recommended_followup_shards) -join ', '))",
        "- Failed: $((@($payload.failed_shards) -join ', '))",
        "",
        "| Shard | Status | Seconds |",
        "| --- | --- | --- |"
    )
    foreach ($result in @($Results | Sort-Object -Property duration_seconds -Descending)) {
        $lines += "| $($result.id) | $($result.status) | $($result.duration_seconds) |"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resolvedMarkdownPath) | Out-Null
    $lines | Set-Content -Path $resolvedMarkdownPath -Encoding utf8

    return $payload
}
$shards = @(
    (New-Shard -Id "api" -Label "API endpoints and Portal surface" -PytestArgs @("tests/test_api.py")),
    (New-Shard -Id "p19_cli_contracts" -Label "P19 replay, CLI, contracts, and Godot CLI" -PytestArgs @("tests/test_godot_cli.py", "tests/test_game_creation_wizard.py", "tests/test_contracts.py", "tests/test_cli.py")),
    (New-Shard -Id "resource_quality" -Label "Resource, performance, layout, art, and balance" -PytestArgs @("tests/test_build_run_matrix.py", "tests/test_performance_pipeline.py", "tests/test_project_layout.py", "tests/test_art_pipeline.py", "tests/test_asset_review.py", "tests/test_balance_analysis.py")),
    (New-Shard -Id "telemetry_templates" -Label "Telemetry, templates, LiveOps, platform, presentation, and quality dashboard" -PytestArgs @("tests/test_telemetry_pipeline.py", "tests/test_liveops_pipeline_skill.py", "tests/test_platform_delivery_skill.py", "tests/test_presentation_pipeline_skill.py", "tests/test_quality_dashboard.py", "tests/test_template_registry.py", "tests/test_gameplay_template_skill.py", "tests/test_level_workflow.py", "tests/test_data_pipeline.py")),
    (New-Shard -Id "agent_mcp" -Label "Agent router, MCP, skill migrations, bootstrap, and cleanup" -PytestArgs @("tests/test_agent.py", "tests/test_agent_compatibility.py", "tests/test_remote_mcp_bridge.py", "tests/test_mcp_server.py", "tests/test_skill_result_migrations.py", "tests/test_skill_regressions.py", "tests/test_context_logic.py", "tests/test_integration.py", "tests/test_runtime_artifact_cleanup.py", "tests/test_clean_machine_bootstrap.py")),
    (New-Shard -Id "release_foundation" -Label "Release candidate, distribution, request auth, capability, delivery readiness, and runtime assembly" -PytestArgs @("tests/test_release_candidate.py", "tests/test_release_capability_policy.py", "tests/test_release_capability_registry.py", "tests/test_release_delivery_readiness.py", "tests/test_release_distribution.py", "tests/test_release_request_auth.py", "tests/test_release_runtime_assembly.py")),
    (New-Shard -Id "release_ci_support" -Label "Release CI support artifacts, event stream, runner baseline, and scene ownership" -PytestArgs @("tests/test_release_ci_artifacts.py", "tests/test_release_live_event_stream.py", "tests/test_release_live_runner_baseline.py", "tests/test_scene_ownership.py")),
    (New-Shard -Id "release_live_ci" -Label "Release live CI local replay artifacts" -PytestArgs @("tests/test_release_live_ci_artifacts.py")),
    (New-Shard -Id "release_execution" -Label "Release execution and rollout control" -PytestArgs @("tests/test_release_execution.py")),
    (New-Shard -Id "promotion_core" -Label "Release promotion core and repository sample" -PytestArgs @("tests/test_release_promotion.py", "-k", "record_release_promotion or release_promotion_blocks or report_builders or threads_distribution or repository_sample")),
    (New-Shard -Id "promotion_api_export" -Label "Release promotion API shape and export reports" -PytestArgs @("tests/test_release_promotion.py", "-k", "release_promotion_api_shape or export_endpoints or review_bundle")),
    (New-Shard -Id "promotion_history" -Label "Release promotion history APIs and reports" -PytestArgs @("tests/test_release_promotion.py", "-k", "history")),
    (New-Shard -Id "promotion_target" -Label "Release target strict gate checks" -PytestArgs @("tests/test_release_promotion.py", "-k", "release_target")),
    (New-Shard -Id "promotion_redacted" -Label "Release promotion redacted auth report" -PytestArgs @("tests/test_release_promotion.py", "-k", "prefers_redacted"))
)

$profileShardIds = @{
    quick = @("api", "p19_cli_contracts", "resource_quality", "telemetry_templates", "agent_mcp")
    release = @("release_foundation", "release_ci_support", "release_live_ci", "release_execution", "promotion_core", "promotion_api_export", "promotion_history", "promotion_target", "promotion_redacted")
    customer = @("api", "p19_cli_contracts", "resource_quality", "agent_mcp", "release_foundation")
}

if (-not [string]::IsNullOrWhiteSpace($Shard)) {
    $requested = @($Shard.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $knownShardIds = @($shards | ForEach-Object { $_.id })
    $shards = @($shards | Where-Object { $requested -contains $_.id })
    if ($shards.Count -ne $requested.Count) {
        $known = ($knownShardIds -join ", ")
        throw "Unknown shard requested. Known shards: $known"
    }
} elseif ($Profile -ne "all") {
    $selectedIds = @($profileShardIds[$Profile])
    $shards = @($shards | Where-Object { $selectedIds -contains $_.id })
}

if ($Preview) {
    [ordered]@{
        schema_version = "1.0"
        ok = $true
        preview = $true
        status = "preview"
        report_state = "preview"
        profile = $Profile
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        python_command = $resolvedPython
        python_path = $resolvedPythonPath
        report_path = $resolvedReportPath
        markdown_path = $resolvedMarkdownPath
        shard_timeout_seconds = $ShardTimeoutSeconds
        slow_shard_threshold_seconds = $SlowShardSeconds
        fail_on_slow_shards = [bool]$FailOnSlowShards
        planned_shard_count = @($shards).Count
        completed_shard_count = 0
        pending_shard_count = @($shards).Count
        pending_shards = @($shards | ForEach-Object { $_.id })
        shard_count = @($shards).Count
        passed_count = 0
        blocked_count = 0
        timeout_count = 0
        status_counts = [ordered]@{
            passed = 0
            blocked = 0
            timeout = 0
        }
        total_duration_seconds = 0.0
        slow_shard_gate = "preview"
        slow_shards = @()
        recommended_followup_shards = @()
        failed_shards = @()
        results = @()
        shards = $shards
    } | ConvertTo-Json -Depth 8
    exit 0
}

Push-Location $repoRoot
try {
    $previousPythonPath = $env:PYTHONPATH
    if (-not [string]::IsNullOrWhiteSpace($resolvedPythonPath)) {
        $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
            $resolvedPythonPath
        } else {
            $resolvedPythonPath + [System.IO.Path]::PathSeparator + $previousPythonPath
        }
    }
    $results = @()
    $startedAt = (Get-Date).ToUniversalTime().ToString("o")
    $overallOk = $true
    foreach ($entry in $shards) {
        $args = @("-m", "pytest") + @($entry.pytest_args) + $commonArgs
        $argumentText = (@($args) | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join " "
        $start = Get-Date
        $stdoutPath = "$env:TEMP\non_live_$($entry.id)_stdout.txt"
        $stderrPath = "$env:TEMP\non_live_$($entry.id)_stderr.txt"
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
        $process = Start-Process -FilePath $resolvedPython -ArgumentList $argumentText -NoNewWindow -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        $completed = $process.WaitForExit([Math]::Max(1, $ShardTimeoutSeconds) * 1000)
        if (-not $completed) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            $process.WaitForExit()
        }
        $process.Refresh()
        $duration = [Math]::Round(((Get-Date) - $start).TotalSeconds, 2)
        $stdout = if (Test-Path $stdoutPath) { [System.IO.File]::ReadAllText($stdoutPath) } else { "" }
        $stderr = if (Test-Path $stderrPath) { [System.IO.File]::ReadAllText($stderrPath) } else { "" }
        $exitCode = if ($completed) { [int]$process.ExitCode } else { 124 }
        $passed = ($completed -and $exitCode -eq 0)
        if (-not $passed) {
            $overallOk = $false
        }
        $results += [pscustomobject][ordered]@{
            id = $entry.id
            label = $entry.label
            status = if ($passed) { "passed" } elseif (-not $completed) { "timeout" } else { "blocked" }
            exit_code = $exitCode
            duration_seconds = $duration
            pytest_args = @($entry.pytest_args)
            stdout_tail = if ($stdout.Length -gt 4000) { $stdout.Substring($stdout.Length - 4000) } else { $stdout }
            stderr_tail = if ($stderr.Length -gt 4000) { $stderr.Substring($stderr.Length - 4000) } else { $stderr }
        }
        Write-NonLiveValidationReport -Results $results -OverallOk $overallOk -StartedAt $startedAt -ReportState "running" | Out-Null
        if (-not $passed -and -not $ContinueOnFailure) {
            break
        }
    }

    $payload = Write-NonLiveValidationReport -Results $results -OverallOk $overallOk -StartedAt $startedAt -ReportState "complete"
    $payload | ConvertTo-Json -Depth 8
    if (-not $payload.ok) {
        exit 1
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}
