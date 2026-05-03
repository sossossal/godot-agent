param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$RuntimeRoot = "",
    [string]$RunnerLabels = '["self-hosted","windows","godot"]',
    [string]$TargetChannel = "release",
    [string]$TargetEnvironment = "production",
    [string]$ReleaseManifestPath = "api_server/static/dist/release_manifest.json",
    [string]$RunnerProfilePath = "deployment/release_live_runner_profile.json",
    [string]$Approvers = "",
    [string]$Providers = "codex,openai_api",
    [string]$ArtifactDir = "logs/reports/release_live_ci_local",
    [string]$BrowserPath = "",
    [string]$PythonCommand = "",
    [string]$ConfigPath = "config.yaml",
    [string]$LiveValidationScriptPath = "tools/run_full_live_validation.ps1",
    [string]$StepSummaryPath = "",
    [string]$PreflightReportPath = "logs/reports/release_live_ci_local_preflight.json",
    [string]$PreflightMarkdownPath = "logs/reports/release_live_ci_local_preflight.md",
    [string]$WorkflowName = "release-live-gates(local)",
    [string]$JobName = "live-release-gates-local",
    [string]$InvocationSource = "local_replay",
    [string]$ExecutedBy = "local_release_runner",
    [string]$Note = "local release-live-gates replay",
    [switch]$PrepareReleaseFixture,
    [switch]$FailOnWarnings,
    [switch]$Preflight,
    [switch]$Preview
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

function Resolve-OptionalPath {
    param(
        [string]$BasePath,
        [string]$RawPath
    )

    if ([string]::IsNullOrWhiteSpace($RawPath)) {
        return ""
    }

    if ([System.IO.Path]::IsPathRooted($RawPath)) {
        return [System.IO.Path]::GetFullPath($RawPath)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $RawPath))
}

function Get-StepDefinition {
    param(
        [string]$Id,
        [string]$Label,
        [string]$Command,
        [string[]]$Arguments,
        [bool]$AlwaysRun = $false
    )

    return [ordered]@{
        id = $Id
        label = $Label
        command = $Command
        arguments = @($Arguments)
        always_run = $AlwaysRun
    }
}

function Invoke-StepCommand {
    param(
        [string]$StepId,
        [string]$Command,
        [string[]]$Arguments
    )

    $capturedOutput = @(& $Command @Arguments 2>&1)
    $outputText = (($capturedOutput | ForEach-Object { [string]$_ }) -join [System.Environment]::NewLine).Trim()
    if ($LASTEXITCODE -ne 0) {
        if ($outputText) {
            throw "step '$StepId' failed with exit code $LASTEXITCODE`n$outputText"
        }
        throw "step '$StepId' failed with exit code $LASTEXITCODE"
    }
    return $outputText
}

function Read-JsonFile {
    param(
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path $Path)) {
        return $null
    }

    try {
        return Get-Content -Raw -Path $Path -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Write-JsonFile {
    param(
        [string]$Path,
        [object]$Payload
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $Payload | ConvertTo-Json -Depth 8 | Set-Content -Path $Path -Encoding utf8
}

function New-PreflightCheck {
    param(
        [string]$Id,
        [string]$Status,
        [string]$Message,
        [string]$Path = "",
        [string]$Remediation = ""
    )

    return [ordered]@{
        id = $Id
        status = $Status
        message = $Message
        path = $Path
        remediation = $Remediation
    }
}

function Test-CommandAvailable {
    param([string]$Command)

    if ([string]::IsNullOrWhiteSpace($Command)) {
        return $false
    }

    if ([System.IO.Path]::IsPathRooted($Command) -or $Command.Contains("\") -or $Command.Contains("/")) {
        return Test-Path $Command
    }

    return $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

function Get-PreflightStatus {
    param([object[]]$Checks)

    if (@($Checks | Where-Object { $_.status -eq "blocked" }).Count -gt 0) {
        return "blocked"
    }
    if (@($Checks | Where-Object { $_.status -eq "warning" }).Count -gt 0) {
        return "warning"
    }
    return "passed"
}

$toolRepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedProjectRoot = (Resolve-Path $ProjectRoot).Path
$resolvedRuntimeRoot = if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $resolvedProjectRoot
} else {
    (Resolve-Path $RuntimeRoot).Path
}
$resolvedArtifactDir = Resolve-OptionalPath -BasePath $resolvedRuntimeRoot -RawPath $ArtifactDir
$resolvedLiveValidationScriptPath = Resolve-OptionalPath -BasePath $resolvedProjectRoot -RawPath $LiveValidationScriptPath
$resolvedPreflightReportPath = Resolve-OptionalPath -BasePath $resolvedRuntimeRoot -RawPath $PreflightReportPath
$resolvedPreflightMarkdownPath = Resolve-OptionalPath -BasePath $resolvedRuntimeRoot -RawPath $PreflightMarkdownPath
$resolvedFixtureReportPath = Join-Path $resolvedRuntimeRoot "logs\reports\release_live_fixture.json"
$resolvedFixtureMarkdownPath = Join-Path $resolvedRuntimeRoot "logs\reports\release_live_fixture.md"
$resolvedStepSummaryPath = if ([string]::IsNullOrWhiteSpace($StepSummaryPath)) {
    Join-Path $resolvedArtifactDir "release_live_ci_step_summary.md"
} else {
    Resolve-OptionalPath -BasePath $resolvedRuntimeRoot -RawPath $StepSummaryPath
}
$resolvedWorkflowStepResultsPath = Join-Path $resolvedRuntimeRoot "logs\reports\release_live_ci_workflow_steps.json"
$resolvedPythonCommand = if (-not [string]::IsNullOrWhiteSpace($PythonCommand)) {
    $PythonCommand
} elseif (-not [string]::IsNullOrWhiteSpace($env:PYTHON)) {
    $env:PYTHON
} else {
    "python"
}
$normalizedRunnerLabels = $RunnerLabels
if (-not [string]::IsNullOrWhiteSpace($RunnerLabels)) {
    try {
        $parsedRunnerLabels = $RunnerLabels | ConvertFrom-Json
        if ($parsedRunnerLabels -is [System.Collections.IEnumerable] -and -not ($parsedRunnerLabels -is [string])) {
            $normalizedRunnerLabels = (($parsedRunnerLabels | ForEach-Object { [string]$_ }) -join ",")
        }
    } catch {
        $normalizedRunnerLabels = $RunnerLabels
    }
}

$baselineArgs = @(
    (Join-Path $toolRepoRoot "tools\export_release_live_runner_baseline.py"),
    "--project-root", $resolvedProjectRoot,
    "--runtime-root", $resolvedRuntimeRoot,
    "--channel", $TargetChannel,
    "--target-environment", $TargetEnvironment,
    "--release-manifest-path", $ReleaseManifestPath,
    "--runner-profile-path", $RunnerProfilePath,
    "--config-path", $ConfigPath,
    "--declared-runner-labels", $normalizedRunnerLabels,
    "--fail-on-blockers"
)
if (-not [string]::IsNullOrWhiteSpace($BrowserPath)) {
    $baselineArgs += @("--browser-path", $BrowserPath)
}

$handoffArgs = @(
    (Join-Path $toolRepoRoot "tools\export_release_distribution_handoff.py"),
    "--project-root", $resolvedProjectRoot,
    "--runtime-root", $resolvedRuntimeRoot,
    "--channel", $TargetChannel,
    "--target-environment", $TargetEnvironment,
    "--release-manifest-path", $ReleaseManifestPath
)

$signingHandoffArgs = @(
    (Join-Path $toolRepoRoot "tools\export_release_distribution_signing_handoff.py"),
    "--project-root", $resolvedProjectRoot,
    "--runtime-root", $resolvedRuntimeRoot,
    "--channel", $TargetChannel,
    "--target-environment", $TargetEnvironment,
    "--release-manifest-path", $ReleaseManifestPath
)

$publishHandoffArgs = @(
    (Join-Path $toolRepoRoot "tools\export_release_distribution_publish_handoff.py"),
    "--project-root", $resolvedProjectRoot,
    "--runtime-root", $resolvedRuntimeRoot,
    "--channel", $TargetChannel,
    "--target-environment", $TargetEnvironment,
    "--release-manifest-path", $ReleaseManifestPath
)

$identityHandoffArgs = @(
    (Join-Path $toolRepoRoot "tools\export_release_request_auth_identity_handoff.py"),
    "--project-root", $resolvedProjectRoot,
    "--runtime-root", $resolvedRuntimeRoot,
    "--channel", $TargetChannel,
    "--target-environment", $TargetEnvironment,
    "--release-manifest-path", $ReleaseManifestPath
)

$liveCiArgs = @(
    (Join-Path $toolRepoRoot "tools\export_release_live_ci_artifacts.py"),
    "--project-root", $resolvedProjectRoot,
    "--runtime-root", $resolvedRuntimeRoot,
    "--output-dir", $resolvedArtifactDir,
    "--channel", $TargetChannel,
    "--target-environment", $TargetEnvironment,
    "--release-manifest-path", $ReleaseManifestPath,
    "--mode", "strict",
    "--executed-by", $ExecutedBy,
    "--note", $Note,
    "--invocation-source", $InvocationSource,
    "--workflow-step-results-path", $resolvedWorkflowStepResultsPath,
    "--fail-on-blockers"
)
if (-not [string]::IsNullOrWhiteSpace($Approvers)) {
    $liveCiArgs += @("--approvers", $Approvers)
}
if (-not [string]::IsNullOrWhiteSpace($Providers)) {
    $liveCiArgs += @("--providers", $Providers)
}
if ($FailOnWarnings) {
    $liveCiArgs += "--fail-on-warnings"
}

$prepareFixtureArgs = @(
    (Join-Path $toolRepoRoot "tools\prepare_release_live_fixture.py"),
    "--channel", $TargetChannel,
    "--scope", "full",
    "--report-path", $resolvedFixtureReportPath,
    "--markdown-path", $resolvedFixtureMarkdownPath
)

$liveValidationArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $resolvedLiveValidationScriptPath,
    "-ReleaseManifestPath", $ReleaseManifestPath
)
if (-not [string]::IsNullOrWhiteSpace($BrowserPath)) {
    $liveValidationArgs += @("-BrowserPath", $BrowserPath)
}

$steps = @()
if ($PrepareReleaseFixture) {
    $steps += Get-StepDefinition -Id "prepare_release_fixture" -Label "Prepare staging release fixture" -Command $resolvedPythonCommand -Arguments $prepareFixtureArgs
}
$steps += @(
    (Get-StepDefinition -Id "export_runner_baseline" -Label "Export release-live runner baseline" -Command $resolvedPythonCommand -Arguments $baselineArgs),
    (Get-StepDefinition -Id "build_distribution_handoff" -Label "Build verified release distribution handoff" -Command $resolvedPythonCommand -Arguments $handoffArgs),
    (Get-StepDefinition -Id "build_distribution_signing_handoff" -Label "Build external signing handoff package" -Command $resolvedPythonCommand -Arguments $signingHandoffArgs),
    (Get-StepDefinition -Id "build_distribution_publish_handoff" -Label "Build external publish handoff package" -Command $resolvedPythonCommand -Arguments $publishHandoffArgs),
    (Get-StepDefinition -Id "build_request_auth_identity_handoff" -Label "Build release request-auth identity handoff" -Command $resolvedPythonCommand -Arguments $identityHandoffArgs),
    (Get-StepDefinition -Id "run_full_live_validation" -Label "Run full live validation" -Command "powershell" -Arguments $liveValidationArgs),
    (Get-StepDefinition -Id "export_live_ci_artifacts" -Label "Export live release CI artifacts" -Command $resolvedPythonCommand -Arguments $liveCiArgs -AlwaysRun $true)
)

$resolvedReleaseManifestPath = Resolve-OptionalPath -BasePath $resolvedRuntimeRoot -RawPath $ReleaseManifestPath
$resolvedRunnerProfilePath = Resolve-OptionalPath -BasePath $resolvedRuntimeRoot -RawPath $RunnerProfilePath
$resolvedConfigPath = Resolve-OptionalPath -BasePath $resolvedProjectRoot -RawPath $ConfigPath
$requiredRunnerLabels = @("self-hosted", "windows", "godot")
$actualRunnerLabels = @(
    $normalizedRunnerLabels.Split(",") |
        ForEach-Object { $_.Trim().ToLowerInvariant() } |
        Where-Object { $_ }
)
$missingRunnerLabels = @($requiredRunnerLabels | Where-Object { $actualRunnerLabels -notcontains $_ })
$preflightChecks = @()
$preflightChecks += if (Test-Path $resolvedProjectRoot) {
    New-PreflightCheck -Id "project_root" -Status "passed" -Message "project root exists" -Path $resolvedProjectRoot
} else {
    New-PreflightCheck -Id "project_root" -Status "blocked" -Message "project root is missing" -Path $resolvedProjectRoot -Remediation "Pass -ProjectRoot with an existing Godot Agent project checkout."
}
$preflightChecks += if (Test-Path $resolvedRuntimeRoot) {
    New-PreflightCheck -Id "runtime_root" -Status "passed" -Message "runtime root exists" -Path $resolvedRuntimeRoot
} else {
    New-PreflightCheck -Id "runtime_root" -Status "blocked" -Message "runtime root is missing" -Path $resolvedRuntimeRoot -Remediation "Pass -RuntimeRoot with an existing runtime directory, or omit it to use the project root."
}
$preflightChecks += if (Test-CommandAvailable $resolvedPythonCommand) {
    New-PreflightCheck -Id "python_command" -Status "passed" -Message "python command is available" -Path $resolvedPythonCommand
} else {
    New-PreflightCheck -Id "python_command" -Status "blocked" -Message "python command is not available" -Path $resolvedPythonCommand -Remediation "Install Python 3.12 or pass -PythonCommand with the full path to python.exe."
}
$preflightChecks += if (Test-CommandAvailable "powershell") {
    New-PreflightCheck -Id "powershell_command" -Status "passed" -Message "PowerShell command is available" -Path "powershell"
} else {
    New-PreflightCheck -Id "powershell_command" -Status "blocked" -Message "PowerShell command is not available" -Path "powershell" -Remediation "Run this gate from Windows PowerShell or ensure powershell.exe is available on PATH."
}
$preflightChecks += if (Test-Path $resolvedLiveValidationScriptPath) {
    New-PreflightCheck -Id "live_validation_script" -Status "passed" -Message "live validation script exists" -Path $resolvedLiveValidationScriptPath
} else {
    New-PreflightCheck -Id "live_validation_script" -Status "blocked" -Message "live validation script is missing" -Path $resolvedLiveValidationScriptPath -Remediation "Restore tools/run_full_live_validation.ps1 or pass -LiveValidationScriptPath to the intended script."
}
$preflightChecks += if (Test-Path $resolvedReleaseManifestPath) {
    New-PreflightCheck -Id "release_manifest" -Status "passed" -Message "release manifest exists" -Path $resolvedReleaseManifestPath
} elseif ($PrepareReleaseFixture) {
    New-PreflightCheck -Id "release_manifest" -Status "warning" -Message "release manifest is missing; fixture preparation is planned" -Path $resolvedReleaseManifestPath -Remediation "Run without -Preflight so -PrepareReleaseFixture can create the synthetic release manifest."
} else {
    New-PreflightCheck -Id "release_manifest" -Status "blocked" -Message "release manifest is missing" -Path $resolvedReleaseManifestPath -Remediation "Create a release manifest first, or pass -ReleaseManifestPath to an existing api_server/static/dist/.../release_manifest.json."
}
$preflightChecks += if (Test-Path $resolvedRunnerProfilePath) {
    New-PreflightCheck -Id "runner_profile" -Status "passed" -Message "runner profile exists" -Path $resolvedRunnerProfilePath
} else {
    New-PreflightCheck -Id "runner_profile" -Status "warning" -Message "runner profile is missing; baseline export will regenerate it" -Path $resolvedRunnerProfilePath -Remediation "Run tools/export_release_live_runner_baseline.py or let the full local gate regenerate this file."
}
$preflightChecks += if (Test-Path $resolvedConfigPath) {
    New-PreflightCheck -Id "config" -Status "passed" -Message "config path exists" -Path $resolvedConfigPath
} else {
    New-PreflightCheck -Id "config" -Status "warning" -Message "config path is missing; Godot/browser checks may be incomplete" -Path $resolvedConfigPath -Remediation "Create config.yaml or pass -ConfigPath to the intended config file."
}
if ([string]::IsNullOrWhiteSpace($BrowserPath)) {
    $preflightChecks += New-PreflightCheck -Id "browser_path" -Status "warning" -Message "browser path is not set; browser live lanes may be skipped" -Path "" -Remediation "Pass -BrowserPath with Chrome or Edge when browser live lanes are required."
} else {
    $resolvedBrowserPath = Resolve-OptionalPath -BasePath $resolvedProjectRoot -RawPath $BrowserPath
    $preflightChecks += if (Test-Path $resolvedBrowserPath) {
        New-PreflightCheck -Id "browser_path" -Status "passed" -Message "browser path exists" -Path $resolvedBrowserPath
    } else {
        New-PreflightCheck -Id "browser_path" -Status "blocked" -Message "browser path is missing" -Path $resolvedBrowserPath -Remediation "Install Chrome or Edge, or pass -BrowserPath to an existing browser executable."
    }
}
$preflightChecks += if ($missingRunnerLabels.Count -eq 0) {
    New-PreflightCheck -Id "runner_labels" -Status "passed" -Message "runner labels include release-live requirements" -Path $normalizedRunnerLabels
} else {
    New-PreflightCheck -Id "runner_labels" -Status "warning" -Message ("runner labels missing: " + ($missingRunnerLabels -join ", ")) -Path $normalizedRunnerLabels -Remediation "Use runner labels that include self-hosted, windows, and godot for release-live-gates."
}
$preflightStatus = Get-PreflightStatus -Checks $preflightChecks
$preflightPayload = [ordered]@{
    schema_version = "1.0"
    status = $preflightStatus
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    project_root = $resolvedProjectRoot
    runtime_root = $resolvedRuntimeRoot
    blocking_checks = @($preflightChecks | Where-Object { $_.status -eq "blocked" } | ForEach-Object { $_.id })
    warning_checks = @($preflightChecks | Where-Object { $_.status -eq "warning" } | ForEach-Object { $_.id })
    checks = $preflightChecks
}

if ($Preflight) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resolvedPreflightReportPath) | Out-Null
    $preflightPayload | ConvertTo-Json -Depth 8 | Set-Content -Path $resolvedPreflightReportPath -Encoding utf8

    $preflightLines = @(
        "# Release Live Local Preflight",
        "",
        "- Status: $($preflightPayload.status)",
        "- Blocking: $((@($preflightPayload.blocking_checks) -join ', '))",
        "- Warning: $((@($preflightPayload.warning_checks) -join ', '))",
        "",
        "| Check | Status | Message | Remediation |",
        "| --- | --- | --- | --- |"
    )
    foreach ($check in $preflightChecks) {
        $preflightLines += "| $($check.id) | $($check.status) | $($check.message) | $($check.remediation) |"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resolvedPreflightMarkdownPath) | Out-Null
    $preflightLines | Set-Content -Path $resolvedPreflightMarkdownPath -Encoding utf8
}

if ($Preview -or $Preflight) {
    [ordered]@{
        ok = if ($Preview -and -not $Preflight) { $true } else { ($preflightStatus -ne "blocked") }
        preview = $true
        preflight = [bool]$Preflight
        preflight_status = $preflightStatus
        preflight_checks = $preflightPayload
        project_root = $resolvedProjectRoot
        runtime_root = $resolvedRuntimeRoot
        artifact_dir = $resolvedArtifactDir
        prepare_release_fixture = [bool]$PrepareReleaseFixture
        release_live_fixture_report_path = $resolvedFixtureReportPath
        release_live_fixture_markdown_path = $resolvedFixtureMarkdownPath
        step_summary_path = $resolvedStepSummaryPath
        preflight_report_path = $resolvedPreflightReportPath
        preflight_markdown_path = $resolvedPreflightMarkdownPath
        workflow_step_results_path = $resolvedWorkflowStepResultsPath
        invocation_source = $InvocationSource
        workflow_name = $WorkflowName
        job_name = $JobName
        steps = $steps
    } | ConvertTo-Json -Depth 8
    if ($Preflight -and $preflightStatus -eq "blocked") {
        exit 1
    }
    return
}

$previousEnv = [ordered]@{
    RUNNER_NAME = $env:RUNNER_NAME
    RUNNER_OS = $env:RUNNER_OS
    RUNNER_ARCH = $env:RUNNER_ARCH
    GITHUB_ACTIONS = $env:GITHUB_ACTIONS
    GITHUB_WORKFLOW = $env:GITHUB_WORKFLOW
    GITHUB_JOB = $env:GITHUB_JOB
    GITHUB_RUN_ID = $env:GITHUB_RUN_ID
    GITHUB_RUN_ATTEMPT = $env:GITHUB_RUN_ATTEMPT
    RELEASE_LIVE_GATES_PROJECT_ROOT = $env:RELEASE_LIVE_GATES_PROJECT_ROOT
    RELEASE_LIVE_GATES_RUNTIME_ROOT = $env:RELEASE_LIVE_GATES_RUNTIME_ROOT
}

$runId = "local-" + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$summaryJsonPath = Join-Path $resolvedArtifactDir "release_live_ci_summary.json"
$summaryMarkdownPath = Join-Path $resolvedArtifactDir "release_live_ci_summary.md"

try {
    if ([string]::IsNullOrWhiteSpace($env:RUNNER_NAME)) {
        $env:RUNNER_NAME = [System.Environment]::GetEnvironmentVariable("COMPUTERNAME")
    }
    if ([string]::IsNullOrWhiteSpace($env:RUNNER_OS)) {
        $env:RUNNER_OS = "Windows"
    }
    if ([string]::IsNullOrWhiteSpace($env:RUNNER_ARCH)) {
        $env:RUNNER_ARCH = [System.Environment]::GetEnvironmentVariable("PROCESSOR_ARCHITECTURE")
    }
    if ([string]::IsNullOrWhiteSpace($env:GITHUB_WORKFLOW)) {
        $env:GITHUB_WORKFLOW = $WorkflowName
    }
    if ([string]::IsNullOrWhiteSpace($env:GITHUB_JOB)) {
        $env:GITHUB_JOB = $JobName
    }
    if ([string]::IsNullOrWhiteSpace($env:GITHUB_RUN_ID)) {
        $env:GITHUB_RUN_ID = $runId
    }
    if ([string]::IsNullOrWhiteSpace($env:GITHUB_RUN_ATTEMPT)) {
        $env:GITHUB_RUN_ATTEMPT = "1"
    }

    $env:RELEASE_LIVE_GATES_PROJECT_ROOT = $resolvedProjectRoot
    $env:RELEASE_LIVE_GATES_RUNTIME_ROOT = $resolvedRuntimeRoot

    $stepResults = @()
    $failedStepIds = @()
    $firstFailureStepId = ""
    $firstFailureMessage = ""
    foreach ($step in $steps) {
        $isAlwaysRun = [bool]$step.always_run
        if (-not [string]::IsNullOrWhiteSpace($firstFailureStepId) -and -not $isAlwaysRun) {
            $stepResults += [ordered]@{
                step_id = $step.id
                label = $step.label
                status = "skipped"
                outcome = "skipped"
                always_run = $isAlwaysRun
                message = "skipped after previous step failure"
                output_preview = ""
            }
            continue
        }

        if ([string]$step.id -eq "export_live_ci_artifacts") {
            Write-JsonFile -Path $resolvedWorkflowStepResultsPath -Payload @($stepResults)
        }

        try {
            $stepOutput = Invoke-StepCommand -StepId $step.id -Command $step.command -Arguments $step.arguments
            $stepResults += [ordered]@{
                step_id = $step.id
                label = $step.label
                status = "passed"
                outcome = "success"
                always_run = $isAlwaysRun
                message = ""
                output_preview = if ([string]::IsNullOrWhiteSpace($stepOutput)) {
                    ""
                } elseif ($stepOutput.Length -gt 600) {
                    $stepOutput.Substring(0, 600)
                } else {
                    $stepOutput
                }
            }
        } catch {
            $failureMessage = $_.Exception.Message
            $stepResults += [ordered]@{
                step_id = $step.id
                label = $step.label
                status = "blocked"
                outcome = "failure"
                always_run = $isAlwaysRun
                message = $failureMessage
                output_preview = ""
            }
            $failedStepIds += [string]$step.id
            if ([string]::IsNullOrWhiteSpace($firstFailureStepId)) {
                $firstFailureStepId = [string]$step.id
                $firstFailureMessage = $failureMessage
            }
        }
    }

    if (Test-Path $summaryMarkdownPath) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resolvedStepSummaryPath) | Out-Null
        Get-Content $summaryMarkdownPath | Out-File -FilePath $resolvedStepSummaryPath -Encoding utf8
    }

    $summaryPayload = Read-JsonFile -Path $summaryJsonPath
    $summaryExcerpt = $null
    if ($summaryPayload) {
        $summaryExcerpt = [ordered]@{
            ci_gate = $summaryPayload.ci_gate
            runtime_gates = $summaryPayload.runtime_gates
            runtime_assembly = $summaryPayload.runtime_assembly
            event_stream = $summaryPayload.event_stream
            runtime_lanes = $summaryPayload.runtime_lanes
            workflow_steps = $summaryPayload.workflow_steps
            report_files = $summaryPayload.report_files
        }
    }

    $resultPayload = [ordered]@{
        ok = [string]::IsNullOrWhiteSpace($firstFailureStepId)
        preview = $false
        project_root = $resolvedProjectRoot
        runtime_root = $resolvedRuntimeRoot
        artifact_dir = $resolvedArtifactDir
        summary_path = $summaryJsonPath
        summary_markdown_path = $summaryMarkdownPath
        step_summary_path = $resolvedStepSummaryPath
        workflow_step_results_path = $resolvedWorkflowStepResultsPath
        workflow_context = [ordered]@{
            workflow = $env:GITHUB_WORKFLOW
            job = $env:GITHUB_JOB
            run_id = $env:GITHUB_RUN_ID
            run_attempt = $env:GITHUB_RUN_ATTEMPT
            github_actions = ($env:GITHUB_ACTIONS -eq "true")
        }
        invocation_source = $InvocationSource
        summary_excerpt = $summaryExcerpt
        steps = $steps
        step_results = $stepResults
        failed_step_ids = @($failedStepIds)
    }
    if (-not [string]::IsNullOrWhiteSpace($firstFailureStepId)) {
        $resultPayload.error = $firstFailureMessage
        $resultPayload | ConvertTo-Json -Depth 8
        exit 1
    }

    $resultPayload | ConvertTo-Json -Depth 8
} catch {
    $summaryPayload = Read-JsonFile -Path $summaryJsonPath
    $summaryExcerpt = $null
    if ($summaryPayload) {
        $summaryExcerpt = [ordered]@{
            ci_gate = $summaryPayload.ci_gate
            runtime_gates = $summaryPayload.runtime_gates
            runtime_assembly = $summaryPayload.runtime_assembly
            event_stream = $summaryPayload.event_stream
            runtime_lanes = $summaryPayload.runtime_lanes
            workflow_steps = $summaryPayload.workflow_steps
            report_files = $summaryPayload.report_files
        }
    }

    [ordered]@{
        ok = $false
        preview = $false
        project_root = $resolvedProjectRoot
        runtime_root = $resolvedRuntimeRoot
        artifact_dir = $resolvedArtifactDir
        summary_path = $summaryJsonPath
        summary_markdown_path = $summaryMarkdownPath
        step_summary_path = $resolvedStepSummaryPath
        invocation_source = $InvocationSource
        summary_excerpt = $summaryExcerpt
        error = $_.Exception.Message
        steps = $steps
    } | ConvertTo-Json -Depth 8
    exit 1
} finally {
    foreach ($entry in $previousEnv.GetEnumerator()) {
        if ($null -eq $entry.Value) {
            Remove-Item -Path ("Env:" + $entry.Key) -ErrorAction SilentlyContinue
        } else {
            [System.Environment]::SetEnvironmentVariable($entry.Key, [string]$entry.Value, "Process")
        }
    }
}
