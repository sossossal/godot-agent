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
    [string]$ConfigPath = "config.yaml",
    [string]$LiveValidationScriptPath = "tools/run_full_live_validation.ps1",
    [string]$StepSummaryPath = "",
    [string]$WorkflowName = "release-live-gates(local)",
    [string]$JobName = "live-release-gates-local",
    [string]$InvocationSource = "local_replay",
    [string]$ExecutedBy = "local_release_runner",
    [string]$Note = "local release-live-gates replay",
    [switch]$FailOnWarnings,
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

$toolRepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedProjectRoot = (Resolve-Path $ProjectRoot).Path
$resolvedRuntimeRoot = if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $resolvedProjectRoot
} else {
    (Resolve-Path $RuntimeRoot).Path
}
$resolvedArtifactDir = Resolve-OptionalPath -BasePath $resolvedRuntimeRoot -RawPath $ArtifactDir
$resolvedLiveValidationScriptPath = Resolve-OptionalPath -BasePath $resolvedProjectRoot -RawPath $LiveValidationScriptPath
$resolvedStepSummaryPath = if ([string]::IsNullOrWhiteSpace($StepSummaryPath)) {
    Join-Path $resolvedArtifactDir "release_live_ci_step_summary.md"
} else {
    Resolve-OptionalPath -BasePath $resolvedRuntimeRoot -RawPath $StepSummaryPath
}
$resolvedWorkflowStepResultsPath = Join-Path $resolvedRuntimeRoot "logs\reports\release_live_ci_workflow_steps.json"
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

$liveValidationArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $resolvedLiveValidationScriptPath,
    "-ReleaseManifestPath", $ReleaseManifestPath
)
if (-not [string]::IsNullOrWhiteSpace($BrowserPath)) {
    $liveValidationArgs += @("-BrowserPath", $BrowserPath)
}

$steps = @(
    (Get-StepDefinition -Id "export_runner_baseline" -Label "Export release-live runner baseline" -Command "python" -Arguments $baselineArgs),
    (Get-StepDefinition -Id "build_distribution_handoff" -Label "Build verified release distribution handoff" -Command "python" -Arguments $handoffArgs),
    (Get-StepDefinition -Id "build_distribution_signing_handoff" -Label "Build external signing handoff package" -Command "python" -Arguments $signingHandoffArgs),
    (Get-StepDefinition -Id "build_distribution_publish_handoff" -Label "Build external publish handoff package" -Command "python" -Arguments $publishHandoffArgs),
    (Get-StepDefinition -Id "build_request_auth_identity_handoff" -Label "Build release request-auth identity handoff" -Command "python" -Arguments $identityHandoffArgs),
    (Get-StepDefinition -Id "run_full_live_validation" -Label "Run full live validation" -Command "powershell" -Arguments $liveValidationArgs),
    (Get-StepDefinition -Id "export_live_ci_artifacts" -Label "Export live release CI artifacts" -Command "python" -Arguments $liveCiArgs -AlwaysRun $true)
)

if ($Preview) {
    [ordered]@{
        ok = $true
        preview = $true
        project_root = $resolvedProjectRoot
        runtime_root = $resolvedRuntimeRoot
        artifact_dir = $resolvedArtifactDir
        step_summary_path = $resolvedStepSummaryPath
        workflow_step_results_path = $resolvedWorkflowStepResultsPath
        invocation_source = $InvocationSource
        workflow_name = $WorkflowName
        job_name = $JobName
        steps = $steps
    } | ConvertTo-Json -Depth 8
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
