param(
    [ValidateSet("pr", "merge", "release", "customer")]
    [string]$Stage = "pr",
    [ValidateSet("full", "preflight")]
    [string]$Mode = "full",
    [string]$PythonCommand = "",
    [string]$ArtifactDir = "logs/reports/pr_release_gate",
    [string]$ReleaseManifestPath = "api_server/static/dist/release_manifest.json",
    [string]$BrowserPath = "",
    [int]$SlowShardSeconds = 120,
    [string]$PreparedReleaseChannel = "release",
    [switch]$PrepareReleaseFixture,
    [switch]$RestorePreparedFixture,
    [switch]$FailOnSlowShards,
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

function Resolve-RepoScopedPath {
    param([string]$RawPath)

    $resolved = Resolve-RepoPath $RawPath
    $repoFull = [System.IO.Path]::GetFullPath($repoRoot)
    $repoPrefix = $repoFull.TrimEnd("\", "/") + [System.IO.Path]::DirectorySeparatorChar
    if ($resolved -ne $repoFull -and -not $resolved.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Managed fixture path escapes repository root: $RawPath"
    }
    return $resolved
}

function Get-RepoRelativePath {
    param([string]$FullPath)

    $repoFull = [System.IO.Path]::GetFullPath($repoRoot).TrimEnd("\", "/")
    $resolved = [System.IO.Path]::GetFullPath($FullPath)
    if ($resolved -eq $repoFull) {
        return "."
    }
    return $resolved.Substring($repoFull.Length + 1)
}

function Copy-StateItem {
    param(
        [string]$Source,
        [string]$Destination,
        [string]$Kind
    )

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    if ($Kind -eq "dir") {
        if (Test-Path -LiteralPath $Destination) {
            Remove-Item -LiteralPath $Destination -Recurse -Force
        }
        Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
    } else {
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
    }
}

function Save-PreparedFixtureState {
    param(
        [string[]]$ManagedFiles,
        [string[]]$ManagedDirectories,
        [string]$StateRoot
    )

    if (Test-Path -LiteralPath $StateRoot) {
        Remove-Item -LiteralPath $StateRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
    $snapshots = @()
    foreach ($rawPath in @($ManagedFiles + $ManagedDirectories)) {
        $target = Resolve-RepoScopedPath $rawPath
        $kind = if ($ManagedDirectories -contains $rawPath) { "dir" } else { "file" }
        $exists = Test-Path -LiteralPath $target
        $backupPath = Join-Path $StateRoot (Get-RepoRelativePath $target)
        if ($exists) {
            $actualKind = if ((Get-Item -LiteralPath $target).PSIsContainer) { "dir" } else { "file" }
            Copy-StateItem -Source $target -Destination $backupPath -Kind $actualKind
            $kind = $actualKind
        }
        $snapshots += [ordered]@{
            path = $target
            kind = $kind
            existed = [bool]$exists
            backup_path = $backupPath
        }
    }
    return $snapshots
}

function Restore-PreparedFixtureState {
    param([object[]]$Snapshots)

    $items = @($Snapshots)
    for ($index = $items.Count - 1; $index -ge 0; $index--) {
        $snapshot = $items[$index]
        $target = Resolve-RepoScopedPath ([string]$snapshot.path)
        $kind = [string]$snapshot.kind
        $backupPath = [string]$snapshot.backup_path
        $existed = [bool]$snapshot.existed

        if (Test-Path -LiteralPath $target) {
            if ((Get-Item -LiteralPath $target).PSIsContainer) {
                Remove-Item -LiteralPath $target -Recurse -Force
            } else {
                Remove-Item -LiteralPath $target -Force
            }
        }

        if ($existed -and (Test-Path -LiteralPath $backupPath)) {
            Copy-StateItem -Source $backupPath -Destination $target -Kind $kind
        }
    }
}

function Invoke-GateStep {
    param(
        [string]$Id,
        [string]$Label,
        [string]$Command,
        [string[]]$Arguments,
        [bool]$AllowFailure = $false
    )

    $started = Get-Date
    $captured = @(& $Command @Arguments 2>&1)
    $duration = [Math]::Round(((Get-Date) - $started).TotalSeconds, 2)
    $output = (($captured | ForEach-Object { [string]$_ }) -join [System.Environment]::NewLine).Trim()
    $exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
    $passed = $exitCode -eq 0
    $commandLine = "& " + $Command + " " + (($Arguments | ForEach-Object { [string]$_ }) -join " ")
    $failureHint = ""
    if (-not $passed -and $output -match "ModuleNotFoundError: No module named '([^']+)'") {
        $failureHint = "Python dependency '$($Matches[1])' is missing; install requirements.txt before this gate step."
    }
    return [ordered]@{
        id = $Id
        label = $Label
        status = if ($passed) { "passed" } elseif ($AllowFailure) { "warning" } else { "blocked" }
        exit_code = $exitCode
        duration_seconds = $duration
        command_line = $commandLine.Trim()
        failure_hint = $failureHint
        output_tail = if ($output.Length -gt 4000) { $output.Substring($output.Length - 4000) } else { $output }
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

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedArtifactDir = Resolve-RepoPath $ArtifactDir
$jsonReportPath = Join-Path $resolvedArtifactDir "gate_summary.json"
$markdownReportPath = Join-Path $resolvedArtifactDir "gate_summary.md"
$nonLiveReportPath = Join-Path $resolvedArtifactDir "non_live_validation_shards.json"
$nonLiveMarkdownPath = Join-Path $resolvedArtifactDir "non_live_validation_shards.md"
$livePreflightReportPath = Join-Path $resolvedArtifactDir "release_live_preflight.json"
$livePreflightMarkdownPath = Join-Path $resolvedArtifactDir "release_live_preflight.md"
$preparedFixtureReportPath = Join-Path $resolvedArtifactDir "release_live_fixture.json"
$preparedFixtureMarkdownPath = Join-Path $resolvedArtifactDir "release_live_fixture.md"
$preparedFixtureStateRoot = Join-Path $resolvedArtifactDir "prepared_fixture_state"
$preparedFixtureManagedFiles = @(
    "deployment/release_live_runner_profile.json",
    "deployment/release_distribution_delivery.json",
    "deployment/release_identity_boundary.json",
    "deployment/release_identity_registry.json",
    "deployment/release_access_policy.json",
    "deployment/release_promotion_history.json",
    "deployment/release_execution_status.json",
    "deployment/release_channels.json",
    "logs/reports/clean_machine_bootstrap.json",
    "logs/reports/doctor_self_check.json",
    "logs/reports/full_live_validation.json",
    "logs/reports/release_request_auth_identity_audit_staging.json",
    "logs/reports/release_request_auth_rotation_audit_staging.json",
    "logs/reports/release_request_auth_posture_promotion_record_staging.json",
    "logs/reports/release_request_auth_posture_release_execution_staging.json",
    "logs/reports/release_distribution_bundle_staging.json",
    "logs/reports/release_distribution_install_smoke_staging.json",
    "logs/reports/release_distribution_channel_staging.json",
    "logs/reports/release_distribution_channels/staging/latest.json",
    "logs/reports/release_distribution_channels/staging/releases.json",
    "logs/reports/release_distribution_packages/staging/web-staging-ci-001/release_distribution_bundle.zip",
    "logs/reports/release_distribution_packages/staging/web-staging-ci-001/release_distribution_bundle.sha256",
    "api_server/static/dist/release_manifest.json",
    "api_server/static/dist/release_notes.md",
    "api_server/static/dist/qa_gate_report.md"
)
$preparedFixtureManagedDirectories = @(
    "logs/reports/full_live_validation_lanes",
    "api_server/static/dist/web_release_validation_ci",
    "logs/reports/release_distribution/staging/web-staging-ci-001",
    "logs/reports/release_distribution_packages/staging/web-staging-ci-001",
    "logs/reports/release_distribution_channels/staging",
    "logs/reports/release_distribution_handoff/staging/web-staging-ci-001",
    "logs/reports/release_distribution_signing/staging/web-staging-ci-001",
    "logs/reports/release_distribution_publish/staging/web-staging-ci-001",
    "logs/reports/release_distribution_publish_receipts/staging/web-staging-ci-001",
    "logs/reports/release_request_auth_identity_handoff/staging/staging"
)
$resolvedPython = if (-not [string]::IsNullOrWhiteSpace($PythonCommand)) {
    $PythonCommand
} elseif (-not [string]::IsNullOrWhiteSpace($env:PYTHON)) {
    $env:PYTHON
} else {
    "python"
}
$nonLiveProfile = switch ($Stage) {
    "pr" { "quick" }
    "merge" { "quick" }
    "release" { "release" }
    "customer" { "customer" }
}
$runLivePreflight = $Stage -in @("merge", "release", "customer")
$runGitDiffCheck = $Stage -in @("pr", "merge", "release")
$runNonLive = $Mode -eq "full"
$preparedFixtureScope = if ($Mode -eq "preflight") { "preflight" } else { "full" }

$stepPlan = @()
if ($runGitDiffCheck) {
    $stepPlan += [ordered]@{
        id = "git_diff_check"
        label = "Git whitespace conflict check"
        command = "git"
        arguments = @("diff", "--check")
    }
}
if ($PrepareReleaseFixture) {
    $stepPlan += [ordered]@{
        id = "prepare_release_fixture"
        label = "Prepare local release-live fixture"
        command = $resolvedPython
        arguments = @(
            (Join-Path $repoRoot "tools\prepare_release_live_fixture.py"),
            "--channel", $PreparedReleaseChannel,
            "--scope", $preparedFixtureScope,
            "--report-path", $preparedFixtureReportPath,
            "--markdown-path", $preparedFixtureMarkdownPath
        )
    }
}
$nonLiveArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $repoRoot "tools\run_non_live_validation_shards.ps1"),
    "-PythonCommand", $resolvedPython,
    "-Profile", $nonLiveProfile,
    "-ReportPath", $nonLiveReportPath,
    "-MarkdownPath", $nonLiveMarkdownPath,
    "-SlowShardSeconds", ([string]$SlowShardSeconds)
)
if ($FailOnSlowShards) {
    $nonLiveArgs += "-FailOnSlowShards"
}
if ($ContinueOnFailure) {
    $nonLiveArgs += "-ContinueOnFailure"
}
if ($runNonLive) {
    $stepPlan += [ordered]@{
        id = "non_live_validation"
        label = "Non-live validation shard profile '$nonLiveProfile'"
        command = "powershell"
        arguments = $nonLiveArgs
    }
}
if ($runLivePreflight) {
    $liveArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "tools\run_release_live_gates_locally.ps1"),
        "-PythonCommand", $resolvedPython,
        "-ReleaseManifestPath", $ReleaseManifestPath,
        "-Preflight",
        "-PreflightReportPath", $livePreflightReportPath,
        "-PreflightMarkdownPath", $livePreflightMarkdownPath
    )
    if (-not [string]::IsNullOrWhiteSpace($BrowserPath)) {
        $liveArgs += @("-BrowserPath", $BrowserPath)
    }
    $stepPlan += [ordered]@{
        id = "release_live_preflight"
        label = "Release live local preflight"
        command = "powershell"
        arguments = $liveArgs
    }
}

if ($Preview) {
    [ordered]@{
        ok = $true
        preview = $true
        stage = $Stage
        mode = $Mode
        non_live_profile = $nonLiveProfile
        artifact_dir = $resolvedArtifactDir
        report_path = $jsonReportPath
        markdown_path = $markdownReportPath
        non_live_report_path = $nonLiveReportPath
        prepared_release_fixture_report_path = $preparedFixtureReportPath
        prepared_release_fixture_markdown_path = $preparedFixtureMarkdownPath
        release_live_preflight_report_path = $livePreflightReportPath
        release_manifest_path = $ReleaseManifestPath
        browser_path = $BrowserPath
        fail_on_slow_shards = [bool]$FailOnSlowShards
        continue_on_failure = [bool]$ContinueOnFailure
        prepare_release_fixture = [bool]$PrepareReleaseFixture
        restore_prepared_fixture = [bool]$RestorePreparedFixture
        prepared_release_fixture_state_root = if ($PrepareReleaseFixture -and $RestorePreparedFixture) { $preparedFixtureStateRoot } else { $null }
        prepared_release_channel = $PreparedReleaseChannel
        prepared_release_fixture_scope = $preparedFixtureScope
        steps = $stepPlan
    } | ConvertTo-Json -Depth 8
    exit 0
}

Push-Location $repoRoot
$preparedFixtureSnapshots = @()
$preparedFixtureRestored = $false
try {
    New-Item -ItemType Directory -Force -Path $resolvedArtifactDir | Out-Null
    if ($PrepareReleaseFixture -and $RestorePreparedFixture) {
        $preparedFixtureSnapshots = Save-PreparedFixtureState `
            -ManagedFiles $preparedFixtureManagedFiles `
            -ManagedDirectories $preparedFixtureManagedDirectories `
            -StateRoot $preparedFixtureStateRoot
    }
    $results = @()
    $overallOk = $true
    foreach ($step in $stepPlan) {
        $result = Invoke-GateStep -Id $step.id -Label $step.label -Command $step.command -Arguments $step.arguments
        $results += $result
        if ($result.status -eq "blocked") {
            $overallOk = $false
            if (-not $ContinueOnFailure) {
                break
            }
        }
    }
    if ($PrepareReleaseFixture -and $RestorePreparedFixture -and @($preparedFixtureSnapshots).Count -gt 0) {
        Restore-PreparedFixtureState -Snapshots $preparedFixtureSnapshots
        $preparedFixtureRestored = $true
    }

    $nonLiveReport = Read-JsonFile -Path $nonLiveReportPath
    $preparedFixtureReport = Read-JsonFile -Path $preparedFixtureReportPath
    $livePreflightReport = Read-JsonFile -Path $livePreflightReportPath
    foreach ($result in $results) {
        if ($result.id -eq "release_live_preflight" -and $result.status -eq "blocked" -and $livePreflightReport) {
            $blockingChecks = @($livePreflightReport.blocking_checks)
            if ($blockingChecks.Count -gt 0 -and [string]::IsNullOrWhiteSpace([string]$result.failure_hint)) {
                $result.failure_hint = "Live preflight blocked checks: $((@($blockingChecks) -join ', ')). See $livePreflightReportPath."
            }
        }
        if ($result.id -eq "non_live_validation" -and $result.status -eq "blocked" -and $nonLiveReport) {
            $failedShards = @($nonLiveReport.failed_shards)
            if ($failedShards.Count -gt 0 -and [string]::IsNullOrWhiteSpace([string]$result.failure_hint)) {
                $result.failure_hint = "Non-live failed shards: $((@($failedShards) -join ', ')). See $nonLiveReportPath."
            }
        }
    }
    $evidence = [ordered]@{
        prepared_release_fixture = if ($preparedFixtureReport) {
            [ordered]@{
                status = if ([bool]$preparedFixtureReport.ok) { "passed" } else { "blocked" }
                fixture_scope = [string]$preparedFixtureReport.fixture_scope
                channel = [string]$preparedFixtureReport.channel
                build_id = [string]$preparedFixtureReport.build_id
                version = [string]$preparedFixtureReport.version
                manifest_path = [string]$preparedFixtureReport.manifest_path
                report_path = $preparedFixtureReportPath
                markdown_path = $preparedFixtureMarkdownPath
            }
        } else {
            $null
        }
        non_live = if ($nonLiveReport) {
            [ordered]@{
                status = [string]$nonLiveReport.status
                profile = [string]$nonLiveReport.profile
                shard_count = [int]$nonLiveReport.shard_count
                total_duration_seconds = [double]$nonLiveReport.total_duration_seconds
                slow_shard_gate = [string]$nonLiveReport.slow_shard_gate
                fail_on_slow_shards = [bool]$nonLiveReport.fail_on_slow_shards
                failed_shards = @($nonLiveReport.failed_shards)
                slow_shards = @($nonLiveReport.slow_shards | ForEach-Object { $_.id })
                report_path = $nonLiveReportPath
                markdown_path = $nonLiveMarkdownPath
            }
        } else {
            $null
        }
        release_live_preflight = if ($livePreflightReport) {
            [ordered]@{
                status = [string]$livePreflightReport.status
                blocking_checks = @($livePreflightReport.blocking_checks)
                warning_checks = @($livePreflightReport.warning_checks)
                report_path = $livePreflightReportPath
                markdown_path = $livePreflightMarkdownPath
            }
        } else {
            $null
        }
    }

    $payload = [ordered]@{
        schema_version = "1.0"
        ok = $overallOk
        status = if ($overallOk) { "passed" } else { "blocked" }
        stage = $Stage
        mode = $Mode
        non_live_profile = $nonLiveProfile
        release_manifest_path = $ReleaseManifestPath
        browser_path = $BrowserPath
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        artifact_dir = $resolvedArtifactDir
        blocked_steps = @($results | Where-Object { $_.status -eq "blocked" } | ForEach-Object { $_.id })
        warning_steps = @($results | Where-Object { $_.status -eq "warning" } | ForEach-Object { $_.id })
        evidence = $evidence
        results = $results
        continue_on_failure = [bool]$ContinueOnFailure
        prepare_release_fixture = [bool]$PrepareReleaseFixture
        prepared_release_channel = $PreparedReleaseChannel
        prepared_release_fixture_scope = $preparedFixtureScope
        restore_prepared_fixture = [bool]$RestorePreparedFixture
        prepared_fixture_restored = $preparedFixtureRestored
    }
    $payload | ConvertTo-Json -Depth 8 | Set-Content -Path $jsonReportPath -Encoding utf8

    $lines = @(
        "# PR Release Gate",
        "",
        "- Stage: $Stage",
        "- Mode: $Mode",
        "- Status: $($payload.status)",
        "- Non-live profile: $nonLiveProfile",
        "- Release manifest: $ReleaseManifestPath",
        "- Browser path: $BrowserPath",
        "- Blocked: $((@($payload.blocked_steps) -join ', '))",
        "- Warnings: $((@($payload.warning_steps) -join ', '))",
        "- Continue on failure: $([bool]$ContinueOnFailure)",
        "- Prepare release fixture: $([bool]$PrepareReleaseFixture)",
        "- Prepared release channel: $PreparedReleaseChannel",
        "- Prepared fixture scope: $preparedFixtureScope",
        "- Restore prepared fixture: $([bool]$RestorePreparedFixture)",
        "- Prepared fixture restored: $preparedFixtureRestored",
        "- Prepared fixture: $($evidence.prepared_release_fixture.status)",
        "- Prepared fixture report: $($evidence.prepared_release_fixture.report_path)",
        "- Prepared fixture markdown: $($evidence.prepared_release_fixture.markdown_path)",
        "- Fail on slow shards: $([bool]$FailOnSlowShards)",
        "- Non-live slow shard gate: $($evidence.non_live.slow_shard_gate)",
        "- Non-live failed shards: $((@($evidence.non_live.failed_shards) -join ', '))",
        "- Non-live slow shards: $((@($evidence.non_live.slow_shards) -join ', '))",
        "- Live preflight: $($evidence.release_live_preflight.status)",
        "",
        "| Step | Status | Seconds |",
        "| --- | --- | --- |"
    )
    foreach ($result in $results) {
        $lines += "| $($result.id) | $($result.status) | $($result.duration_seconds) |"
    }
    $diagnosticResults = @($results | Where-Object { $_.status -ne "passed" -or -not [string]::IsNullOrWhiteSpace([string]$_.failure_hint) })
    if ($diagnosticResults.Count -gt 0) {
        $lines += @(
            "",
            "## Step Diagnostics",
            ""
        )
        foreach ($result in $diagnosticResults) {
            $lines += "### $($result.id)"
            $lines += ""
            $lines += "- Status: $($result.status)"
            if (-not [string]::IsNullOrWhiteSpace([string]$result.failure_hint)) {
                $lines += "- Failure hint: $($result.failure_hint)"
            }
            if (-not [string]::IsNullOrWhiteSpace([string]$result.command_line)) {
                $lines += "- Command: ``$($result.command_line)``"
            }
            if (-not [string]::IsNullOrWhiteSpace([string]$result.output_tail)) {
                $lines += ""
                $lines += '```text'
                $lines += [string]$result.output_tail
                $lines += '```'
            }
            $lines += ""
        }
    }
    $lines | Set-Content -Path $markdownReportPath -Encoding utf8

    $payload | ConvertTo-Json -Depth 8
    if (-not $overallOk) {
        exit 1
    }
} finally {
    if ($PrepareReleaseFixture -and $RestorePreparedFixture -and -not $preparedFixtureRestored -and @($preparedFixtureSnapshots).Count -gt 0) {
        Restore-PreparedFixtureState -Snapshots $preparedFixtureSnapshots
        $preparedFixtureRestored = $true
    }
    Pop-Location
}
