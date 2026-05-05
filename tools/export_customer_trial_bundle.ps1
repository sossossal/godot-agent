param(
    [string]$PythonCommand = "",
    [string]$OutputDir = "logs/reports/customer_trial_bundle",
    [string]$ReleaseManifestPath = "api_server/static/dist/release_manifest.json",
    [string]$BrowserPath = "",
    [switch]$PrepareReleaseFixture,
    [switch]$RestorePreparedFixture,
    [switch]$SyncPluginBeforeDoctor,
    [ValidateSet("preflight", "full")]
    [string]$GateMode = "preflight",
    [switch]$FailOnNeedsAttention,
    [switch]$ContinueOnFailure,
    [switch]$Preview
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

function Resolve-RepoPath {
    param([string]$RawPath)

    if ([System.IO.Path]::IsPathRooted($RawPath)) {
        return [System.IO.Path]::GetFullPath($RawPath)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $RawPath))
}

function ConvertTo-ProcessArgument {
    param([string]$Value)

    $text = [string]$Value
    if ($text -notmatch "[\s']") {
        return $text
    }
    return "'" + ($text -replace "'", "''") + "'"
}

function Invoke-BundleStep {
    param(
        [string]$Id,
        [string]$Label,
        [string]$Command,
        [string[]]$Arguments
    )

    $started = Get-Date
    $captured = @(& $Command @Arguments 2>&1)
    $duration = [Math]::Round(((Get-Date) - $started).TotalSeconds, 2)
    $output = (($captured | ForEach-Object { [string]$_ }) -join [System.Environment]::NewLine).Trim()
    $exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
    return [ordered]@{
        id = $Id
        label = $Label
        status = if ($exitCode -eq 0) { "passed" } else { "blocked" }
        exit_code = $exitCode
        duration_seconds = $duration
        output_tail = if ($output.Length -gt 3000) { $output.Substring($output.Length - 3000) } else { $output }
    }
}

function Copy-EvidenceFile {
    param(
        [string]$SourcePath,
        [string]$RelativeDestination
    )

    $source = Resolve-RepoPath $SourcePath
    if (-not (Test-Path $source)) {
        return $null
    }
    $destination = Join-Path $resolvedOutputDir $RelativeDestination
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    if ([System.IO.Path]::GetFullPath($source) -ne [System.IO.Path]::GetFullPath($destination)) {
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
    return [ordered]@{
        source = $source
        path = $destination
        relative_path = $RelativeDestination.Replace("\", "/")
    }
}

function Read-JsonFile {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $null
    }
    try {
        return Get-Content -Raw -Path $Path -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Format-ListOrNone {
    param([object[]]$Items)

    $values = @($Items)
    if ($values.Count -eq 0) {
        return "None"
    }
    return $values -join ", "
}

function Format-MapOrNone {
    param([object]$Map)

    if ($null -eq $Map -or @($Map.Keys).Count -eq 0) {
        return "None"
    }
    return (@($Map.Keys) | ForEach-Object { "$_=$($Map[$_])" }) -join ", "
}

function Get-EvidenceCompleteness {
    param(
        [object[]]$EvidenceFiles,
        [string[]]$AssumePresentPaths = @()
    )

    $assumed = @($AssumePresentPaths | ForEach-Object { [System.IO.Path]::GetFullPath([string]$_) })
    $missing = @(
        $EvidenceFiles |
            Where-Object {
                $path = [System.IO.Path]::GetFullPath([string]$_.path)
                ($assumed -notcontains $path) -and -not (Test-Path -LiteralPath $path)
            } |
            ForEach-Object { [string]$_.relative_path }
    )
    $count = @($EvidenceFiles).Count
    return [ordered]@{
        evidence_file_count = $count
        evidence_present_count = $count - @($missing).Count
        missing_evidence_count = @($missing).Count
        missing_evidence_files = $missing
        evidence_status_counts = [ordered]@{
            present = $count - @($missing).Count
            missing = @($missing).Count
        }
    }
}

function Get-ActionSourceCounts {
    param([object[]]$Items)

    $counts = [ordered]@{}
    foreach ($item in @($Items)) {
        $source = [string]$item.source
        if ([string]::IsNullOrWhiteSpace($source)) {
            $source = "unknown"
        }
        if (-not $counts.Contains($source)) {
            $counts[$source] = 0
        }
        $counts[$source] = [int]$counts[$source] + 1
    }
    return $counts
}

function Get-NonLiveSummary {
    param([object]$GateReport)

    if ($null -eq $GateReport -or $null -eq $GateReport.evidence -or $null -eq $GateReport.evidence.non_live) {
        return $null
    }
    $nonLive = $GateReport.evidence.non_live
    return [ordered]@{
        status = [string]$nonLive.status
        report_state = [string]$nonLive.report_state
        profile = [string]$nonLive.profile
        planned_shard_count = [int]$nonLive.planned_shard_count
        completed_shard_count = [int]$nonLive.completed_shard_count
        pending_shard_count = [int]$nonLive.pending_shard_count
        pending_shards = @($nonLive.pending_shards)
        passed_count = [int]$nonLive.passed_count
        blocked_count = [int]$nonLive.blocked_count
        timeout_count = [int]$nonLive.timeout_count
        status_counts = $nonLive.status_counts
        failed_shards = @($nonLive.failed_shards)
        slow_shards = @($nonLive.slow_shards)
        report_path = [string]$nonLive.report_path
        markdown_path = [string]$nonLive.markdown_path
    }
}

function Get-GateSummary {
    param([object]$GateReport)

    if ($null -eq $GateReport) {
        return $null
    }
    return [ordered]@{
        status = [string]$GateReport.status
        stage = [string]$GateReport.stage
        mode = [string]$GateReport.mode
        non_live_profile = [string]$GateReport.non_live_profile
        blocked_steps = @($GateReport.blocked_steps)
        warning_steps = @($GateReport.warning_steps)
        planned_step_count = [int]$GateReport.planned_step_count
        planned_step_ids = @($GateReport.planned_step_ids)
        skipped_step_count = [int]$GateReport.skipped_step_count
        skipped_step_ids = @($GateReport.skipped_step_ids)
        step_count = [int]$GateReport.step_count
        step_ids = @($GateReport.step_ids)
        passed_count = [int]$GateReport.passed_count
        blocked_count = [int]$GateReport.blocked_count
        warning_count = [int]$GateReport.warning_count
        status_counts = $GateReport.status_counts
        total_duration_seconds = [double]$GateReport.total_duration_seconds
        slowest_step_id = [string]$GateReport.slowest_step_id
        slowest_step_seconds = [double]$GateReport.slowest_step_seconds
        report_path = Join-Path $gateArtifactDir "gate_summary.json"
        markdown_path = Join-Path $gateArtifactDir "gate_summary.md"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedOutputDir = Resolve-RepoPath $OutputDir
$resolvedPython = if (-not [string]::IsNullOrWhiteSpace($PythonCommand)) {
    $PythonCommand
} elseif (-not [string]::IsNullOrWhiteSpace($env:PYTHON)) {
    $env:PYTHON
} else {
    "python"
}
$gateArtifactDir = Join-Path $resolvedOutputDir "gate"
$manifestPath = Join-Path $resolvedOutputDir "customer_trial_bundle_manifest.json"
$markdownPath = Join-Path $resolvedOutputDir "customer_trial_bundle.md"
$rerunScriptPath = Join-Path $resolvedOutputDir "rerun_customer_trial.ps1"
$commandManifestPath = Join-Path $resolvedOutputDir "customer_trial_commands.json"
$readinessSummaryPath = Join-Path $resolvedOutputDir "customer_trial_readiness.json"
$steps = @()
if ($SyncPluginBeforeDoctor) {
    $steps += [ordered]@{
        id = "sync_plugin"
        label = "Sync Godot plugin copies"
        command = "powershell"
        arguments = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", (Join-Path $repoRoot "tools\sync_plugin.ps1"),
            "-RepoRoot", $repoRoot
        )
    }
}
$steps += @(
    [ordered]@{
        id = "doctor"
        label = "Run doctor self-check"
        command = $resolvedPython
        arguments = @("-m", "agent_system.cli", "doctor")
    },
    [ordered]@{
        id = "customer_gate"
        label = "Run customer trial gate"
        command = "powershell"
        arguments = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", (Join-Path $repoRoot "tools\run_pr_release_gate.ps1"),
            "-Stage", "customer",
            "-Mode", $GateMode,
            "-PythonCommand", $resolvedPython,
            "-ReleaseManifestPath", $ReleaseManifestPath,
            "-ArtifactDir", $gateArtifactDir
        )
    }
)
if ($ContinueOnFailure) {
    $steps[-1].arguments += "-ContinueOnFailure"
}
if (-not [string]::IsNullOrWhiteSpace($BrowserPath)) {
    $steps[-1].arguments += @("-BrowserPath", $BrowserPath)
}
if ($PrepareReleaseFixture) {
    $steps[-1].arguments += "-PrepareReleaseFixture"
}
if ($RestorePreparedFixture) {
    $steps[-1].arguments += "-RestorePreparedFixture"
}

$commandRecords = @()
foreach ($step in $steps) {
    $commandLine = "& " + (ConvertTo-ProcessArgument -Value $step.command)
    foreach ($argument in $step.arguments) {
        $commandLine += " " + (ConvertTo-ProcessArgument -Value $argument)
    }
    $commandRecords += [ordered]@{
        id = $step.id
        label = $step.label
        command = $step.command
        arguments = $step.arguments
        command_line = $commandLine
    }
}
$commandIds = @($commandRecords | ForEach-Object { $_.id })
$plannedStepIds = @($steps | ForEach-Object { $_.id })

if ($Preview) {
    $previewLivePreflightSummary = [ordered]@{
        status = "preview"
        check_count = 0
        passed_count = 0
        blocking_count = 0
        warning_count = 0
        status_counts = [ordered]@{
            passed = 0
            blocked = 0
            warning = 0
        }
        blocking_checks = @()
        warning_checks = @()
        report_path = Join-Path $gateArtifactDir "release_live_preflight.json"
        markdown_path = Join-Path $gateArtifactDir "release_live_preflight.md"
    }
    $previewGateSummary = $null
    $previewNonLiveSummary = $null
    $previewReadinessSummary = [ordered]@{
        schema_version = "1.0"
        status = "preview"
        readiness_level = "preview"
        ok = $true
        gate_mode = $GateMode
        release_manifest_path = $ReleaseManifestPath
        browser_path = $BrowserPath
        fail_on_needs_attention = [bool]$FailOnNeedsAttention
        continue_on_failure = [bool]$ContinueOnFailure
        should_fail_on_needs_attention = $false
        blocked_steps = @()
        passed_count = 0
        blocked_count = 0
        status_counts = [ordered]@{
            passed = 0
            blocked = 0
        }
        total_duration_seconds = 0.0
        slowest_step_id = ""
        slowest_step_seconds = 0.0
        planned_step_count = @($steps).Count
        planned_step_ids = $plannedStepIds
        skipped_step_count = 0
        skipped_step_ids = @()
        step_count = @($steps).Count
        step_ids = $plannedStepIds
        recommended_action_count = 0
        recommended_actions = @()
        recommended_action_items = @()
        recommended_action_source_counts = [ordered]@{}
        rerun_summary = [ordered]@{
            command_count = @($commandRecords).Count
            command_ids = $commandIds
            blocked_command_count = 0
            blocked_command_ids = @()
            blocked_commands = @()
            missing_blocked_step_count = 0
            missing_blocked_step_ids = @()
            recommended_command_count = 0
            recommended_commands = @()
        }
        gate_summary = $previewGateSummary
        live_preflight_summary = $previewLivePreflightSummary
        non_live_summary = $previewNonLiveSummary
        evidence_file_count = 0
        evidence_present_count = 0
        missing_evidence_count = 0
        evidence_status_counts = [ordered]@{
            present = 0
            missing = 0
        }
        evidence_files = @()
        missing_evidence_files = @()
        command_count = @($commandRecords).Count
        command_ids = $commandIds
        rerun_script_path = $rerunScriptPath
        command_manifest_path = $commandManifestPath
        generated_at = ""
    }
    [ordered]@{
        schema_version = "1.0"
        ok = $true
        preview = $true
        status = "preview"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        project_root = $repoRoot
        output_dir = $resolvedOutputDir
        manifest_path = $manifestPath
        markdown_path = $markdownPath
        rerun_script_path = $rerunScriptPath
        command_manifest_path = $commandManifestPath
        readiness_summary_path = $readinessSummaryPath
        release_manifest_path = $ReleaseManifestPath
        gate_mode = $GateMode
        browser_path = $BrowserPath
        blocked_steps = @()
        passed_count = 0
        blocked_count = 0
        status_counts = [ordered]@{
            passed = 0
            blocked = 0
        }
        total_duration_seconds = 0.0
        slowest_step_id = ""
        slowest_step_seconds = 0.0
        fail_on_needs_attention = [bool]$FailOnNeedsAttention
        continue_on_failure = [bool]$ContinueOnFailure
        should_fail_on_needs_attention = $false
        readiness_level = "preview"
        recommended_action_count = 0
        recommended_actions = @()
        recommended_action_items = @()
        recommended_action_source_counts = $previewReadinessSummary.recommended_action_source_counts
        rerun_summary = $previewReadinessSummary.rerun_summary
        readiness_summary = $previewReadinessSummary
        gate_summary = $previewGateSummary
        live_preflight_summary = $previewLivePreflightSummary
        non_live_summary = $previewNonLiveSummary
        evidence_file_count = 0
        evidence_present_count = 0
        missing_evidence_count = 0
        evidence_status_counts = [ordered]@{
            present = 0
            missing = 0
        }
        evidence_files = @()
        missing_evidence_files = @()
        prepare_release_fixture = [bool]$PrepareReleaseFixture
        restore_prepared_fixture = [bool]$RestorePreparedFixture
        sync_plugin_before_doctor = [bool]$SyncPluginBeforeDoctor
        command_count = @($commandRecords).Count
        planned_step_count = @($steps).Count
        planned_step_ids = $plannedStepIds
        skipped_step_count = 0
        skipped_step_ids = @()
        step_count = @($steps).Count
        command_ids = $commandIds
        step_ids = $plannedStepIds
        results = @()
        command_records = $commandRecords
        steps = $steps
    } | ConvertTo-Json -Depth 8
    exit 0
}

Push-Location $repoRoot
try {
    New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null
    $results = @()
    $overallOk = $true
    foreach ($step in $steps) {
        $result = Invoke-BundleStep -Id $step.id -Label $step.label -Command $step.command -Arguments $step.arguments
        $results += $result
        if ($result.status -eq "blocked") {
            $overallOk = $false
            if (-not $ContinueOnFailure) {
                break
            }
        }
    }

    $evidenceFiles = @(
        Copy-EvidenceFile -SourcePath "logs/reports/doctor_self_check.json" -RelativeDestination "runtime_reports\doctor_self_check.json"
        Copy-EvidenceFile -SourcePath "logs/reports/clean_machine_bootstrap.json" -RelativeDestination "runtime_reports\clean_machine_bootstrap.json"
        Copy-EvidenceFile -SourcePath (Join-Path $gateArtifactDir "release_live_fixture.json") -RelativeDestination "gate\release_live_fixture.json"
        Copy-EvidenceFile -SourcePath (Join-Path $gateArtifactDir "release_live_fixture.md") -RelativeDestination "gate\release_live_fixture.md"
        Copy-EvidenceFile -SourcePath (Join-Path $gateArtifactDir "gate_summary.json") -RelativeDestination "gate\gate_summary.json"
        Copy-EvidenceFile -SourcePath (Join-Path $gateArtifactDir "gate_summary.md") -RelativeDestination "gate\gate_summary.md"
        Copy-EvidenceFile -SourcePath (Join-Path $gateArtifactDir "release_live_preflight.json") -RelativeDestination "gate\release_live_preflight.json"
        Copy-EvidenceFile -SourcePath (Join-Path $gateArtifactDir "release_live_preflight.md") -RelativeDestination "gate\release_live_preflight.md"
        Copy-EvidenceFile -SourcePath (Join-Path $gateArtifactDir "non_live_validation_shards.json") -RelativeDestination "gate\non_live_validation_shards.json"
        Copy-EvidenceFile -SourcePath (Join-Path $gateArtifactDir "non_live_validation_shards.md") -RelativeDestination "gate\non_live_validation_shards.md"
    ) | Where-Object { $null -ne $_ }

    $rerunLines = @(
        "param()",
        "",
        '$ErrorActionPreference = "Stop"',
        ("Set-Location " + (ConvertTo-ProcessArgument -Value $repoRoot)),
        ""
    )
    foreach ($step in $steps) {
        $commandRecord = @($commandRecords | Where-Object { $_.id -eq $step.id } | Select-Object -First 1)[0]
        $rerunLines += "# $($step.label)"
        $rerunLines += $commandRecord.command_line
        $rerunLines += ""
    }
    $rerunLines | Set-Content -Path $rerunScriptPath -Encoding utf8
    [ordered]@{
        schema_version = "1.0"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        project_root = $repoRoot
        gate_mode = $GateMode
        browser_path = $BrowserPath
        command_count = @($commandRecords).Count
        command_ids = $commandIds
        commands = $commandRecords
    } | ConvertTo-Json -Depth 8 | Set-Content -Path $commandManifestPath -Encoding utf8
    $evidenceFiles += [ordered]@{
        source = $rerunScriptPath
        path = $rerunScriptPath
        relative_path = "rerun_customer_trial.ps1"
    }
    $evidenceFiles += [ordered]@{
        source = $commandManifestPath
        path = $commandManifestPath
        relative_path = "customer_trial_commands.json"
    }

    $doctorReport = Read-JsonFile -Path (Resolve-RepoPath "logs/reports/doctor_self_check.json")
    $gateReport = Read-JsonFile -Path (Join-Path $gateArtifactDir "gate_summary.json")
    $livePreflightReport = Read-JsonFile -Path (Join-Path $gateArtifactDir "release_live_preflight.json")
    $recommendedActionItems = @()
    if ($livePreflightReport) {
        $recommendedActionItems += @(
            $livePreflightReport.checks |
                Where-Object { $_.status -ne "passed" -and -not [string]::IsNullOrWhiteSpace([string]$_.remediation) } |
                ForEach-Object {
                    [ordered]@{
                        source = "release_live_preflight"
                        check_id = [string]($_.id)
                        check_name = [string]($_.name)
                        title = [string]($_.status)
                        command = ""
                        message = [string]($_.remediation)
                        action = [string]($_.remediation)
                    }
                }
        )
    }
    if ($doctorReport) {
        $recommendedActionItems += @(
            $doctorReport.action_items |
                ForEach-Object {
                    $command = [string]($_.command)
                    $message = [string]($_.message)
                    $actionText = if (-not [string]::IsNullOrWhiteSpace($command)) { $command } else { $message }
                    if (-not [string]::IsNullOrWhiteSpace($actionText)) {
                        [ordered]@{
                            source = "doctor"
                            check_id = [string]($_.check_id)
                            check_name = [string]($_.check_name)
                            title = [string]($_.title)
                            command = $command
                            message = $message
                            action = $actionText
                        }
                    }
                } |
                Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.action) }
        )
    }
    $seenRecommendedActions = @{}
    $recommendedActionItems = @(
        $recommendedActionItems |
            Where-Object {
                $key = [string]$_.action
                if ([string]::IsNullOrWhiteSpace($key) -or $seenRecommendedActions.ContainsKey($key)) {
                    return $false
                }
                $seenRecommendedActions[$key] = $true
                return $true
            }
    )
    $recommendedActions = @($recommendedActionItems | ForEach-Object { [string]$_.action })
    $recommendedActionSourceCounts = Get-ActionSourceCounts -Items $recommendedActionItems
    $livePreflightSummary = if ($livePreflightReport) {
        [ordered]@{
            status = [string]$livePreflightReport.status
            check_count = [int]$livePreflightReport.check_count
            passed_count = [int]$livePreflightReport.passed_count
            blocking_count = [int]$livePreflightReport.blocking_count
            warning_count = [int]$livePreflightReport.warning_count
            status_counts = [ordered]@{
                passed = [int]$livePreflightReport.status_counts.passed
                blocked = [int]$livePreflightReport.status_counts.blocked
                warning = [int]$livePreflightReport.status_counts.warning
            }
            blocking_checks = @($livePreflightReport.blocking_checks)
            warning_checks = @($livePreflightReport.warning_checks)
            report_path = Join-Path $gateArtifactDir "release_live_preflight.json"
            markdown_path = Join-Path $gateArtifactDir "release_live_preflight.md"
        }
    } else {
        $null
    }
    $gateSummary = Get-GateSummary -GateReport $gateReport
    $nonLiveSummary = Get-NonLiveSummary -GateReport $gateReport
    $readinessLevel = if (-not $overallOk) {
        "blocked"
    } elseif (@($recommendedActions).Count -gt 0) {
        "needs_attention"
    } else {
        "ready"
    }
    $shouldFailOnNeedsAttention = [bool]($FailOnNeedsAttention -and $readinessLevel -ne "ready")
    $bundleOk = [bool]($overallOk -and -not $shouldFailOnNeedsAttention)
    $bundleStatus = if (-not $overallOk) {
        "blocked"
    } elseif ($shouldFailOnNeedsAttention) {
        "needs_attention"
    } else {
        "passed"
    }
    $readinessEvidenceFiles = @(
        $evidenceFiles |
            ForEach-Object {
                [ordered]@{
                    source = [string]$_.source
                    path = [string]$_.path
                    relative_path = [string]$_.relative_path
                }
            }
    )
    $readinessEvidenceFiles += [ordered]@{
        source = $readinessSummaryPath
        path = $readinessSummaryPath
        relative_path = "customer_trial_readiness.json"
    }
    $readinessEvidenceCompleteness = Get-EvidenceCompleteness `
        -EvidenceFiles $readinessEvidenceFiles `
        -AssumePresentPaths @($readinessSummaryPath)
    $passedCount = @($results | Where-Object { $_.status -eq "passed" }).Count
    $stepIds = @($results | ForEach-Object { $_.id })
    $skippedStepIds = @($plannedStepIds | Where-Object { $stepIds -notcontains $_ })
    $blockedSteps = @($results | Where-Object { $_.status -eq "blocked" } | ForEach-Object { $_.id })
    $blockedCount = @($results | Where-Object { $_.status -eq "blocked" }).Count
    $blockedCommands = @(
        $blockedSteps |
            ForEach-Object {
                $blockedId = [string]$_
                @($commandRecords | Where-Object { $_.id -eq $blockedId } | Select-Object -First 1)
            } |
            Where-Object { $null -ne $_ }
    )
    $blockedCommandIds = @($blockedCommands | ForEach-Object { [string]$_.id })
    $missingBlockedStepIds = @($blockedSteps | Where-Object { $blockedCommandIds -notcontains [string]$_ })
    $recommendedCommands = @(
        $recommendedActionItems |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.command) } |
            ForEach-Object { [string]$_.command }
    )
    $rerunSummary = [ordered]@{
        command_count = @($commandRecords).Count
        command_ids = $commandIds
        blocked_command_count = @($blockedCommands).Count
        blocked_command_ids = $blockedCommandIds
        blocked_commands = @($blockedCommands)
        missing_blocked_step_count = @($missingBlockedStepIds).Count
        missing_blocked_step_ids = $missingBlockedStepIds
        recommended_command_count = @($recommendedCommands).Count
        recommended_commands = $recommendedCommands
    }
    $totalDurationSeconds = [Math]::Round((@($results | ForEach-Object { [double]$_.duration_seconds }) | Measure-Object -Sum).Sum, 2)
    $slowestStep = @($results | Sort-Object { [double]$_.duration_seconds } -Descending | Select-Object -First 1)
    $statusCounts = [ordered]@{
        passed = $passedCount
        blocked = $blockedCount
    }
    $readinessSummary = [ordered]@{
        schema_version = "1.0"
        status = $bundleStatus
        readiness_level = $readinessLevel
        ok = $bundleOk
        gate_mode = $GateMode
        release_manifest_path = $ReleaseManifestPath
        browser_path = $BrowserPath
        fail_on_needs_attention = [bool]$FailOnNeedsAttention
        continue_on_failure = [bool]$ContinueOnFailure
        should_fail_on_needs_attention = $shouldFailOnNeedsAttention
        blocked_steps = $blockedSteps
        passed_count = $passedCount
        blocked_count = $blockedCount
        status_counts = $statusCounts
        total_duration_seconds = $totalDurationSeconds
        slowest_step_id = if ($slowestStep.Count -gt 0) { [string]$slowestStep[0].id } else { "" }
        slowest_step_seconds = if ($slowestStep.Count -gt 0) { [double]$slowestStep[0].duration_seconds } else { 0.0 }
        planned_step_count = @($steps).Count
        planned_step_ids = $plannedStepIds
        skipped_step_count = @($skippedStepIds).Count
        skipped_step_ids = $skippedStepIds
        step_count = @($results).Count
        step_ids = $stepIds
        recommended_action_count = @($recommendedActions).Count
        recommended_actions = $recommendedActions
        recommended_action_items = $recommendedActionItems
        recommended_action_source_counts = $recommendedActionSourceCounts
        rerun_summary = $rerunSummary
        gate_summary = $gateSummary
        live_preflight_summary = $livePreflightSummary
        non_live_summary = $nonLiveSummary
        evidence_file_count = $readinessEvidenceCompleteness.evidence_file_count
        evidence_present_count = $readinessEvidenceCompleteness.evidence_present_count
        missing_evidence_count = $readinessEvidenceCompleteness.missing_evidence_count
        evidence_status_counts = $readinessEvidenceCompleteness.evidence_status_counts
        evidence_files = $readinessEvidenceFiles
        missing_evidence_files = $readinessEvidenceCompleteness.missing_evidence_files
        command_count = @($commandRecords).Count
        command_ids = $commandIds
        rerun_script_path = $rerunScriptPath
        command_manifest_path = $commandManifestPath
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    $readinessSummary | ConvertTo-Json -Depth 6 | Set-Content -Path $readinessSummaryPath -Encoding utf8
    $evidenceFiles += [ordered]@{
        source = $readinessSummaryPath
        path = $readinessSummaryPath
        relative_path = "customer_trial_readiness.json"
    }
    $evidenceCompleteness = Get-EvidenceCompleteness -EvidenceFiles $evidenceFiles

    $payload = [ordered]@{
        schema_version = "1.0"
        ok = $bundleOk
        status = $bundleStatus
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        project_root = $repoRoot
        output_dir = $resolvedOutputDir
        rerun_script_path = $rerunScriptPath
        command_manifest_path = $commandManifestPath
        readiness_summary_path = $readinessSummaryPath
        gate_mode = $GateMode
        release_manifest_path = $ReleaseManifestPath
        browser_path = $BrowserPath
        fail_on_needs_attention = [bool]$FailOnNeedsAttention
        continue_on_failure = [bool]$ContinueOnFailure
        should_fail_on_needs_attention = $shouldFailOnNeedsAttention
        prepare_release_fixture = [bool]$PrepareReleaseFixture
        restore_prepared_fixture = [bool]$RestorePreparedFixture
        sync_plugin_before_doctor = [bool]$SyncPluginBeforeDoctor
        blocked_steps = $blockedSteps
        passed_count = $passedCount
        blocked_count = $blockedCount
        status_counts = $statusCounts
        recommended_action_count = @($recommendedActions).Count
        recommended_actions = $recommendedActions
        recommended_action_items = $recommendedActionItems
        recommended_action_source_counts = $recommendedActionSourceCounts
        rerun_summary = $rerunSummary
        readiness_level = $readinessLevel
        readiness_summary = $readinessSummary
        gate_summary = $gateSummary
        live_preflight_summary = $livePreflightSummary
        non_live_summary = $nonLiveSummary
        command_count = @($commandRecords).Count
        command_ids = $commandIds
        command_records = $commandRecords
        evidence_file_count = $evidenceCompleteness.evidence_file_count
        evidence_present_count = $evidenceCompleteness.evidence_present_count
        missing_evidence_count = $evidenceCompleteness.missing_evidence_count
        evidence_status_counts = $evidenceCompleteness.evidence_status_counts
        missing_evidence_files = $evidenceCompleteness.missing_evidence_files
        evidence_files = $evidenceFiles
        total_duration_seconds = $totalDurationSeconds
        slowest_step_id = if ($slowestStep.Count -gt 0) { [string]$slowestStep[0].id } else { "" }
        slowest_step_seconds = if ($slowestStep.Count -gt 0) { [double]$slowestStep[0].duration_seconds } else { 0.0 }
        planned_step_count = @($steps).Count
        planned_step_ids = $plannedStepIds
        skipped_step_count = @($skippedStepIds).Count
        skipped_step_ids = $skippedStepIds
        step_count = @($results).Count
        step_ids = $stepIds
        results = $results
    }
    $payload | ConvertTo-Json -Depth 8 | Set-Content -Path $manifestPath -Encoding utf8

    $missingEvidenceLabel = Format-ListOrNone @($payload.missing_evidence_files)
    $plannedStepList = Format-ListOrNone @($payload.planned_step_ids)
    $skippedStepList = Format-ListOrNone @($payload.skipped_step_ids)
    $stepList = Format-ListOrNone @($payload.step_ids)
    $blockedStepList = Format-ListOrNone @($payload.blocked_steps)
    $nonLiveLabel = if ($null -eq $nonLiveSummary) { "None" } else { [string]$nonLiveSummary.status }
    $nonLiveReportState = if ($null -eq $nonLiveSummary) { "None" } else { [string]$nonLiveSummary.report_state }
    $nonLiveCompleted = if ($null -eq $nonLiveSummary) { 0 } else { [int]$nonLiveSummary.completed_shard_count }
    $nonLivePending = if ($null -eq $nonLiveSummary) { 0 } else { [int]$nonLiveSummary.pending_shard_count }
    $nonLivePassed = if ($null -eq $nonLiveSummary) { 0 } else { [int]$nonLiveSummary.passed_count }
    $nonLiveBlocked = if ($null -eq $nonLiveSummary) { 0 } else { [int]$nonLiveSummary.blocked_count }
    $nonLiveTimeout = if ($null -eq $nonLiveSummary) { 0 } else { [int]$nonLiveSummary.timeout_count }
    $nonLivePendingList = if ($null -eq $nonLiveSummary) { "None" } else { Format-ListOrNone @($nonLiveSummary.pending_shards) }
    $nonLiveFailedList = if ($null -eq $nonLiveSummary) { "None" } else { Format-ListOrNone @($nonLiveSummary.failed_shards) }
    $nonLiveSlowList = if ($null -eq $nonLiveSummary) { "None" } else { Format-ListOrNone @($nonLiveSummary.slow_shards) }
    $gateLabel = if ($null -eq $gateSummary) { "None" } else { [string]$gateSummary.status }
    $gateStage = if ($null -eq $gateSummary) { "None" } else { [string]$gateSummary.stage }
    $gateModeLabel = if ($null -eq $gateSummary) { "None" } else { [string]$gateSummary.mode }
    $gateNonLiveProfile = if ($null -eq $gateSummary) { "None" } else { [string]$gateSummary.non_live_profile }
    $gatePlannedSteps = if ($null -eq $gateSummary) { 0 } else { [int]$gateSummary.planned_step_count }
    $gateSkippedSteps = if ($null -eq $gateSummary) { 0 } else { [int]$gateSummary.skipped_step_count }
    $gateExecutedSteps = if ($null -eq $gateSummary) { 0 } else { [int]$gateSummary.step_count }
    $gatePassedSteps = if ($null -eq $gateSummary) { 0 } else { [int]$gateSummary.passed_count }
    $gateBlockedSteps = if ($null -eq $gateSummary) { 0 } else { [int]$gateSummary.blocked_count }
    $gateWarningSteps = if ($null -eq $gateSummary) { 0 } else { [int]$gateSummary.warning_count }
    $gatePlannedStepList = if ($null -eq $gateSummary) { "None" } else { Format-ListOrNone @($gateSummary.planned_step_ids) }
    $gateSkippedStepList = if ($null -eq $gateSummary) { "None" } else { Format-ListOrNone @($gateSummary.skipped_step_ids) }
    $gateExecutedStepList = if ($null -eq $gateSummary) { "None" } else { Format-ListOrNone @($gateSummary.step_ids) }
    $gateBlockedList = if ($null -eq $gateSummary) { "None" } else { Format-ListOrNone @($gateSummary.blocked_steps) }
    $gateWarningList = if ($null -eq $gateSummary) { "None" } else { Format-ListOrNone @($gateSummary.warning_steps) }
    $missingBlockedStepList = Format-ListOrNone @($rerunSummary.missing_blocked_step_ids)
    $recommendedActionSourceLabel = Format-MapOrNone $recommendedActionSourceCounts
    $lines = @(
        "# Customer Trial Bundle",
        "",
        "- Status: $($payload.status)",
        "- Readiness: $readinessLevel",
        "- Gate mode: $GateMode",
        "- Release manifest: $ReleaseManifestPath",
        "- Browser path: $BrowserPath",
        "- Fail on needs attention: $([bool]$FailOnNeedsAttention)",
        "- Should fail on needs attention: $shouldFailOnNeedsAttention",
        "- Continue on failure: $([bool]$ContinueOnFailure)",
        "- Prepare release fixture: $([bool]$PrepareReleaseFixture)",
        "- Restore prepared fixture: $([bool]$RestorePreparedFixture)",
        "- Sync plugin before doctor: $([bool]$SyncPluginBeforeDoctor)",
        "- Total seconds: $($payload.total_duration_seconds)",
        "- Slowest step: $($payload.slowest_step_id) ($($payload.slowest_step_seconds)s)",
        "- Planned steps: $($payload.planned_step_count)",
        "- Planned step ids: $plannedStepList",
        "- Skipped steps: $($payload.skipped_step_count)",
        "- Skipped step ids: $skippedStepList",
        "- Steps: $($payload.step_count)",
        "- Step ids: $stepList",
        "- Passed count: $($payload.passed_count)",
        "- Blocked count: $($payload.blocked_count)",
        "- Blocked: $blockedStepList",
        "- Recommended actions: $($payload.recommended_action_count)",
        "- Recommended action sources: $recommendedActionSourceLabel",
        "- Blocked rerun commands: $($rerunSummary.blocked_command_count)",
        "- Missing blocked rerun commands: $($rerunSummary.missing_blocked_step_count)",
        "- Missing blocked step ids: $missingBlockedStepList",
        "- Recommended command actions: $($rerunSummary.recommended_command_count)",
        "- Gate summary: $gateLabel",
        "- Gate stage: $gateStage",
        "- Gate mode summary: $gateModeLabel",
        "- Gate non-live profile: $gateNonLiveProfile",
        "- Gate planned steps: $gatePlannedSteps",
        "- Gate planned step ids: $gatePlannedStepList",
        "- Gate skipped steps: $gateSkippedSteps",
        "- Gate skipped step ids: $gateSkippedStepList",
        "- Gate executed steps: $gateExecutedSteps",
        "- Gate executed step ids: $gateExecutedStepList",
        "- Gate passed steps: $gatePassedSteps",
        "- Gate blocked step count: $gateBlockedSteps",
        "- Gate warning step count: $gateWarningSteps",
        "- Gate blocked steps: $gateBlockedList",
        "- Gate warning steps: $gateWarningList",
        "- Live preflight: $($livePreflightSummary.status)",
        "- Live preflight checks: $($livePreflightSummary.check_count)",
        "- Live preflight blocking count: $($livePreflightSummary.blocking_count)",
        "- Live preflight warning count: $($livePreflightSummary.warning_count)",
        "- Non-live validation: $nonLiveLabel",
        "- Non-live report state: $nonLiveReportState",
        "- Non-live completed shards: $nonLiveCompleted",
        "- Non-live pending shards: $nonLivePending",
        "- Non-live passed shards: $nonLivePassed",
        "- Non-live blocked shards: $nonLiveBlocked",
        "- Non-live timeout shards: $nonLiveTimeout",
        "- Non-live pending shard ids: $nonLivePendingList",
        "- Non-live failed shard ids: $nonLiveFailedList",
        "- Non-live slow shard ids: $nonLiveSlowList",
        "- Evidence files: $($payload.evidence_file_count)",
        "- Evidence present: $($payload.evidence_present_count)",
        "- Evidence missing: $($payload.missing_evidence_count)",
        "- Rerun commands: $($payload.command_count)",
        "",
        "## Recommended Actions",
        ""
    )
    if ($recommendedActions.Count -eq 0) {
        $lines += "- None"
    } else {
        foreach ($item in $recommendedActionItems) {
            $label = [string]$item.action
            $source = [string]$item.source
            $checkId = [string]$item.check_id
            $sourceLabel = if ([string]::IsNullOrWhiteSpace($checkId)) { $source } else { "$source/$checkId" }
            $lines += "- [$sourceLabel] $label"
        }
    }
    $lines += @(
        "",
        "## Rerun Commands",
        "",
        "| Step | Command |",
        "| --- | --- |"
    )
    foreach ($commandRecord in $commandRecords) {
        $lines += "| $($commandRecord.id) | ``$($commandRecord.command_line)`` |"
    }
    $lines += @(
        "",
        "## Blocked Rerun Commands",
        ""
    )
    if ($rerunSummary.blocked_command_count -eq 0) {
        $lines += "- None"
    } else {
        foreach ($commandRecord in $rerunSummary.blocked_commands) {
            $lines += "### $($commandRecord.id)"
            $lines += ""
            $lines += '```powershell'
            $lines += [string]$commandRecord.command_line
            $lines += '```'
            $lines += ""
        }
    }
    $lines += @(
        "",
        "## Recommended Command Actions",
        ""
    )
    if ($rerunSummary.recommended_command_count -eq 0) {
        $lines += "- None"
    } else {
        foreach ($command in $rerunSummary.recommended_commands) {
            $lines += '```powershell'
            $lines += [string]$command
            $lines += '```'
            $lines += ""
        }
    }
    $blockedResults = @($results | Where-Object { $_.status -eq "blocked" })
    if ($blockedResults.Count -gt 0) {
        $lines += @(
            "",
            "## Blocked Step Output",
            ""
        )
        foreach ($result in $blockedResults) {
            $lines += "### $($result.id)"
            $lines += ""
            if (-not [string]::IsNullOrWhiteSpace([string]$result.output_tail)) {
                $lines += '```text'
                $lines += [string]$result.output_tail
                $lines += '```'
            } else {
                $lines += "- No output captured"
            }
            $lines += ""
        }
    }
    $lines += @(
        "",
        "## Evidence Files",
        "",
        "- Count: $($payload.evidence_file_count)",
        "- Present: $($payload.evidence_present_count)",
        "- Missing count: $($payload.missing_evidence_count)",
        "- Missing: $missingEvidenceLabel",
        "",
        "| Evidence | Path |",
        "| --- | --- |"
    )
    foreach ($file in $evidenceFiles) {
        $lines += "| $($file.relative_path) | $($file.path) |"
    }
    $lines | Set-Content -Path $markdownPath -Encoding utf8

    $payload | ConvertTo-Json -Depth 8
    if (-not $bundleOk) {
        exit 1
    }
} finally {
    Pop-Location
}
