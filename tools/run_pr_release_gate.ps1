param(
    [ValidateSet("pr", "merge", "release", "customer")]
    [string]$Stage = "pr",
    [string]$PythonCommand = "",
    [string]$ArtifactDir = "logs/reports/pr_release_gate",
    [string]$ReleaseManifestPath = "api_server/static/dist/release_manifest.json",
    [string]$BrowserPath = "",
    [int]$SlowShardSeconds = 120,
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

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedArtifactDir = Resolve-RepoPath $ArtifactDir
$jsonReportPath = Join-Path $resolvedArtifactDir "gate_summary.json"
$markdownReportPath = Join-Path $resolvedArtifactDir "gate_summary.md"
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

$stepPlan = @()
if ($runGitDiffCheck) {
    $stepPlan += [ordered]@{
        id = "git_diff_check"
        label = "Git whitespace conflict check"
        command = "git"
        arguments = @("diff", "--check")
    }
}
$nonLiveArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $repoRoot "tools\run_non_live_validation_shards.ps1"),
    "-PythonCommand", $resolvedPython,
    "-Profile", $nonLiveProfile,
    "-ReportPath", (Join-Path $resolvedArtifactDir "non_live_validation_shards.json"),
    "-MarkdownPath", (Join-Path $resolvedArtifactDir "non_live_validation_shards.md"),
    "-SlowShardSeconds", ([string]$SlowShardSeconds)
)
if ($ContinueOnFailure) {
    $nonLiveArgs += "-ContinueOnFailure"
}
$stepPlan += [ordered]@{
    id = "non_live_validation"
    label = "Non-live validation shard profile '$nonLiveProfile'"
    command = "powershell"
    arguments = $nonLiveArgs
}
if ($runLivePreflight) {
    $liveArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "tools\run_release_live_gates_locally.ps1"),
        "-PythonCommand", $resolvedPython,
        "-ReleaseManifestPath", $ReleaseManifestPath,
        "-Preflight",
        "-PreflightReportPath", (Join-Path $resolvedArtifactDir "release_live_preflight.json"),
        "-PreflightMarkdownPath", (Join-Path $resolvedArtifactDir "release_live_preflight.md")
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
        non_live_profile = $nonLiveProfile
        artifact_dir = $resolvedArtifactDir
        report_path = $jsonReportPath
        markdown_path = $markdownReportPath
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

    $payload = [ordered]@{
        schema_version = "1.0"
        ok = $overallOk
        status = if ($overallOk) { "passed" } else { "blocked" }
        stage = $Stage
        non_live_profile = $nonLiveProfile
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        artifact_dir = $resolvedArtifactDir
        blocked_steps = @($results | Where-Object { $_.status -eq "blocked" } | ForEach-Object { $_.id })
        warning_steps = @($results | Where-Object { $_.status -eq "warning" } | ForEach-Object { $_.id })
        results = $results
    }
    $payload | ConvertTo-Json -Depth 8 | Set-Content -Path $jsonReportPath -Encoding utf8

    $lines = @(
        "# PR Release Gate",
        "",
        "- Stage: $Stage",
        "- Status: $($payload.status)",
        "- Non-live profile: $nonLiveProfile",
        "- Blocked: $((@($payload.blocked_steps) -join ', '))",
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
