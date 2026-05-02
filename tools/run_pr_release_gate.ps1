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
    return [ordered]@{
        id = $Id
        label = $Label
        status = if ($passed) { "passed" } elseif ($AllowFailure) { "warning" } else { "blocked" }
        exit_code = $exitCode
        duration_seconds = $duration
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
            "--channel", $PreparedReleaseChannel
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
        release_live_preflight_report_path = $livePreflightReportPath
        fail_on_slow_shards = [bool]$FailOnSlowShards
        prepare_release_fixture = [bool]$PrepareReleaseFixture
        prepared_release_channel = $PreparedReleaseChannel
        steps = $stepPlan
    } | ConvertTo-Json -Depth 8
    exit 0
}

Push-Location $repoRoot
try {
    New-Item -ItemType Directory -Force -Path $resolvedArtifactDir | Out-Null
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

    $nonLiveReport = Read-JsonFile -Path $nonLiveReportPath
    $livePreflightReport = Read-JsonFile -Path $livePreflightReportPath
    $evidence = [ordered]@{
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
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        artifact_dir = $resolvedArtifactDir
        blocked_steps = @($results | Where-Object { $_.status -eq "blocked" } | ForEach-Object { $_.id })
        warning_steps = @($results | Where-Object { $_.status -eq "warning" } | ForEach-Object { $_.id })
        evidence = $evidence
        results = $results
    }
    $payload | ConvertTo-Json -Depth 8 | Set-Content -Path $jsonReportPath -Encoding utf8

    $lines = @(
        "# PR Release Gate",
        "",
        "- Stage: $Stage",
        "- Mode: $Mode",
        "- Status: $($payload.status)",
        "- Non-live profile: $nonLiveProfile",
        "- Blocked: $((@($payload.blocked_steps) -join ', '))",
        "- Prepare release fixture: $([bool]$PrepareReleaseFixture)",
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
    $lines | Set-Content -Path $markdownReportPath -Encoding utf8

    $payload | ConvertTo-Json -Depth 8
    if (-not $overallOk) {
        exit 1
    }
} finally {
    Pop-Location
}
