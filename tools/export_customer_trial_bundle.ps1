param(
    [string]$PythonCommand = "",
    [string]$OutputDir = "logs/reports/customer_trial_bundle",
    [string]$ReleaseManifestPath = "api_server/static/dist/release_manifest.json",
    [switch]$PrepareReleaseFixture,
    [switch]$RestorePreparedFixture,
    [switch]$SyncPluginBeforeDoctor,
    [ValidateSet("preflight", "full")]
    [string]$GateMode = "preflight",
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

if ($Preview) {
    [ordered]@{
        ok = $true
        preview = $true
        output_dir = $resolvedOutputDir
        manifest_path = $manifestPath
        markdown_path = $markdownPath
        rerun_script_path = $rerunScriptPath
        command_manifest_path = $commandManifestPath
        readiness_summary_path = $readinessSummaryPath
        gate_mode = $GateMode
        prepare_release_fixture = [bool]$PrepareReleaseFixture
        restore_prepared_fixture = [bool]$RestorePreparedFixture
        sync_plugin_before_doctor = [bool]$SyncPluginBeforeDoctor
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
    $livePreflightReport = Read-JsonFile -Path (Join-Path $gateArtifactDir "release_live_preflight.json")
    $recommendedActions = @()
    if ($doctorReport) {
        $recommendedActions += @(
            $doctorReport.action_items |
                ForEach-Object {
                    $command = [string]($_.command)
                    $message = [string]($_.message)
                    if (-not [string]::IsNullOrWhiteSpace($command)) {
                        $command
                    } elseif (-not [string]::IsNullOrWhiteSpace($message)) {
                        $message
                    }
                } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
    }
    if ($livePreflightReport) {
        $recommendedActions += @(
            $livePreflightReport.checks |
                Where-Object { $_.status -ne "passed" -and -not [string]::IsNullOrWhiteSpace([string]$_.remediation) } |
                ForEach-Object { [string]$_.remediation }
        )
    }
    $recommendedActions = @($recommendedActions | Select-Object -Unique)
    $readinessSummary = [ordered]@{
        schema_version = "1.0"
        status = if ($overallOk) { "passed" } else { "blocked" }
        ok = $overallOk
        gate_mode = $GateMode
        blocked_steps = @($results | Where-Object { $_.status -eq "blocked" } | ForEach-Object { $_.id })
        recommended_action_count = @($recommendedActions).Count
        evidence_file_count = @($evidenceFiles).Count + 1
        command_count = @($commandRecords).Count
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

    $payload = [ordered]@{
        schema_version = "1.0"
        ok = $overallOk
        status = if ($overallOk) { "passed" } else { "blocked" }
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        project_root = $repoRoot
        output_dir = $resolvedOutputDir
        rerun_script_path = $rerunScriptPath
        command_manifest_path = $commandManifestPath
        readiness_summary_path = $readinessSummaryPath
        gate_mode = $GateMode
        prepare_release_fixture = [bool]$PrepareReleaseFixture
        restore_prepared_fixture = [bool]$RestorePreparedFixture
        sync_plugin_before_doctor = [bool]$SyncPluginBeforeDoctor
        blocked_steps = @($results | Where-Object { $_.status -eq "blocked" } | ForEach-Object { $_.id })
        recommended_actions = $recommendedActions
        readiness_summary = $readinessSummary
        command_records = $commandRecords
        evidence_files = $evidenceFiles
        results = $results
    }
    $payload | ConvertTo-Json -Depth 8 | Set-Content -Path $manifestPath -Encoding utf8

    $lines = @(
        "# Customer Trial Bundle",
        "",
        "- Status: $($payload.status)",
        "- Gate mode: $GateMode",
        "- Prepare release fixture: $([bool]$PrepareReleaseFixture)",
        "- Restore prepared fixture: $([bool]$RestorePreparedFixture)",
        "- Sync plugin before doctor: $([bool]$SyncPluginBeforeDoctor)",
        "- Blocked: $((@($payload.blocked_steps) -join ', '))",
        "",
        "## Recommended Actions",
        ""
    )
    if ($recommendedActions.Count -eq 0) {
        $lines += "- None"
    } else {
        foreach ($action in $recommendedActions) {
            $lines += "- $action"
        }
    }
    $lines += @(
        "",
        "| Evidence | Path |",
        "| --- | --- |"
    )
    foreach ($file in $evidenceFiles) {
        $lines += "| $($file.relative_path) | $($file.path) |"
    }
    $lines | Set-Content -Path $markdownPath -Encoding utf8

    $payload | ConvertTo-Json -Depth 8
    if (-not $overallOk) {
        exit 1
    }
} finally {
    Pop-Location
}
