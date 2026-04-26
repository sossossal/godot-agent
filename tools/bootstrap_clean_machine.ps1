[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$PythonExe = "python",
    [string]$VenvDir = ".venv",
    [switch]$SkipVenv,
    [switch]$SkipInstall,
    [switch]$SkipSyncPlugin,
    [switch]$SkipDoctor,
    [switch]$IncludeSmoke,
    [switch]$Preview,
    [string]$ReportPath,
    [string]$DoctorReportPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [Console]::OutputEncoding

function Ensure-Directory {
    param([string]$PathValue)

    if (-not (Test-Path -LiteralPath $PathValue)) {
        New-Item -ItemType Directory -Force -Path $PathValue | Out-Null
    }
}

function Resolve-AbsolutePath {
    param(
        [string]$BasePath,
        [string]$PathValue
    )

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $PathValue))
}

function Resolve-CommandPath {
    param([string]$CommandOrPath)

    if (-not $CommandOrPath) {
        return $null
    }

    if (Test-Path -LiteralPath $CommandOrPath) {
        return (Resolve-Path -LiteralPath $CommandOrPath).Path
    }

    $command = Get-Command -Name $CommandOrPath -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) {
        return $command.Source
    }

    return $null
}

function Test-VenvReady {
    param([string]$VenvRoot)

    if (-not (Test-Path -LiteralPath $VenvRoot)) {
        return $false
    }

    $venvPython = Join-Path $VenvRoot "Scripts\python.exe"
    $venvPip = Join-Path $VenvRoot "Scripts\pip.exe"
    $venvConfig = Join-Path $VenvRoot "pyvenv.cfg"

    return (Test-Path -LiteralPath $venvPython) -and (Test-Path -LiteralPath $venvPip) -and (Test-Path -LiteralPath $venvConfig)
}

function Format-CommandLine {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    $parts = @($FilePath) + @($Arguments)
    return ($parts | ForEach-Object {
            $value = [string]$_
            if ($value -match '[\s"]') {
                '"' + ($value -replace '"', '\"') + '"'
            } else {
                $value
            }
        }) -join ' '
}

function Get-OutputExcerpt {
    param([string]$Text)

    if (-not $Text) {
        return ""
    }

    $normalized = $Text.Trim()
    if ($normalized.Length -le 1200) {
        return $normalized
    }

    return $normalized.Substring(0, 1200) + "...(truncated)"
}

function Get-DoctorReportSummary {
    param(
        [string]$ResolvedPath,
        [string]$DisplayPath
    )

    $summary = [ordered]@{
        path               = $DisplayPath
        exists             = [bool](Test-Path -LiteralPath $ResolvedPath)
        ok                 = $false
        summary            = ""
        check_count        = 0
        passed_check_count = 0
        failed_check_count = 0
        action_item_count  = 0
        blocking_checks    = @()
    }

    if (-not $summary.exists) {
        return $summary
    }

    try {
        $payload = Get-Content -LiteralPath $ResolvedPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $summary.ok = [bool]$payload.ok
        $summary.summary = [string]$payload.summary
        $summary.check_count = [int]$payload.check_count
        $summary.passed_check_count = [int]$payload.passed_check_count
        $summary.failed_check_count = [int]$payload.failed_check_count
        $summary.action_item_count = [int]$payload.action_item_count
        $summary.blocking_checks = @($payload.blocking_checks)
    } catch {
        $summary.summary = "Unable to parse doctor self-check report."
    }

    return $summary
}

function New-Step {
    param(
        [string]$Id,
        [string]$Title,
        [bool]$Enabled,
        [bool]$Mutates,
        [string]$FilePath,
        [string[]]$Arguments,
        [string[]]$Prerequisites,
        [string]$Notes,
        [string]$Executor
    )

    return [ordered]@{
        id            = $Id
        title         = $Title
        enabled       = $Enabled
        mutates       = $Mutates
        executor      = $Executor
        file_path     = $FilePath
        arguments     = @($Arguments)
        command       = (Format-CommandLine -FilePath $FilePath -Arguments $Arguments)
        prerequisites = @($Prerequisites)
        notes         = $Notes
        status        = if ($Enabled) { "planned" } else { "skipped" }
    }
}

function Invoke-Step {
    param(
        [hashtable]$Step,
        [string]$WorkingDirectory
    )

    $outputText = ""
    $startedAt = Get-Date
    $result = [ordered]@{
        id            = $Step.id
        title         = $Step.title
        enabled       = [bool]$Step.enabled
        mutates       = [bool]$Step.mutates
        executor      = $Step.executor
        command       = $Step.command
        prerequisites = @($Step.prerequisites)
        notes         = $Step.notes
        started_at    = $startedAt.ToString("o")
        status        = "passed"
    }

    if (-not $Step.enabled) {
        $result.status = "skipped"
        return $result
    }

    Push-Location $WorkingDirectory
    try {
        if ($Step.executor -eq "native" -or $Step.executor -eq "powershell") {
            $stdoutPath = Join-Path $WorkspaceTempRoot "$($Step.id)_stdout.log"
            $stderrPath = Join-Path $WorkspaceTempRoot "$($Step.id)_stderr.log"
            Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue

            $launcherPath = $Step.file_path
            $launcherArgs = @($Step.arguments)
            if ($Step.executor -eq "powershell") {
                $launcherPath = "powershell"
                $launcherArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Step.file_path) + @($Step.arguments)
            }

            $process = Start-Process -FilePath $launcherPath `
                -ArgumentList $launcherArgs `
                -WorkingDirectory $WorkingDirectory `
                -Wait `
                -PassThru `
                -NoNewWindow `
                -RedirectStandardOutput $stdoutPath `
                -RedirectStandardError $stderrPath

            $stdoutText = if (Test-Path -LiteralPath $stdoutPath) {
                Get-Content -LiteralPath $stdoutPath -Raw -Encoding UTF8
            } else {
                ""
            }
            $stderrText = if (Test-Path -LiteralPath $stderrPath) {
                Get-Content -LiteralPath $stderrPath -Raw -Encoding UTF8
            } else {
                ""
            }
            $outputText = (@($stdoutText, $stderrText) | Where-Object { $_ }) -join [Environment]::NewLine

            if ($process.ExitCode -ne 0) {
                throw "Command exited with code $($process.ExitCode)"
            }
        } else {
            $outputLines = & $Step.file_path @($Step.arguments) 2>&1
            $outputText = ($outputLines | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
        }
    } catch {
        $result.status = "failed"
        $result.error = $_.Exception.Message
        $result.output_excerpt = Get-OutputExcerpt -Text $outputText
        return $result
    } finally {
        Pop-Location
        $result.finished_at = (Get-Date).ToString("o")
    }

    $result.output_excerpt = Get-OutputExcerpt -Text $outputText
    return $result
}

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
}

$RequirementsPath = Resolve-AbsolutePath -BasePath $RepoRoot -PathValue "requirements.txt"
$ConfigPath = Resolve-AbsolutePath -BasePath $RepoRoot -PathValue "config.yaml"
$SyncScriptPath = Resolve-AbsolutePath -BasePath $RepoRoot -PathValue "tools/sync_plugin.ps1"
$PluginSourcePath = Resolve-AbsolutePath -BasePath $RepoRoot -PathValue "addons/godot_agent"
$VenvPath = Resolve-AbsolutePath -BasePath $RepoRoot -PathValue $VenvDir
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$WorkspaceTempRoot = Resolve-AbsolutePath -BasePath $RepoRoot -PathValue "logs/test_artifacts/bootstrap_tmp"
$VenvReady = Test-VenvReady -VenvRoot $VenvPath
$ResolvedPython = Resolve-CommandPath -CommandOrPath $PythonExe
$SmokePaths = @(
    "tests/test_godot_cli.py",
    "tests/test_cli.py",
    "tests/test_agent_compatibility.py",
    "tests/test_api.py"
)
$SmokeArgs = @("-m", "pytest") + $SmokePaths + @("-q")

if (-not $ReportPath) {
    $ReportPath = "logs/reports/clean_machine_bootstrap.json"
}
$ResolvedReportPath = Resolve-AbsolutePath -BasePath $RepoRoot -PathValue $ReportPath
if (-not $DoctorReportPath) {
    $DoctorReportPath = "logs/reports/doctor_self_check.json"
}
$ResolvedDoctorReportPath = Resolve-AbsolutePath -BasePath $RepoRoot -PathValue $DoctorReportPath

$BlockingIssues = @()
if ((-not $SkipVenv) -or (-not $SkipInstall) -or (-not $SkipDoctor) -or $IncludeSmoke) {
    if (-not $ResolvedPython) {
        $BlockingIssues += [ordered]@{
            code = "python_not_found"
            path = $PythonExe
            message = "Unable to resolve the requested Python launcher."
        }
    }
}

if ((-not $SkipInstall) -and -not (Test-Path -LiteralPath $RequirementsPath)) {
    $BlockingIssues += [ordered]@{
        code = "missing_requirements"
        path = $RequirementsPath
        message = "requirements.txt is required for dependency installation."
    }
}

if ((-not $SkipDoctor) -and -not (Test-Path -LiteralPath $ConfigPath)) {
    $BlockingIssues += [ordered]@{
        code = "missing_config"
        path = $ConfigPath
        message = "config.yaml is required for the default doctor bootstrap flow."
    }
}

if ((-not $SkipSyncPlugin) -and -not (Test-Path -LiteralPath $SyncScriptPath)) {
    $BlockingIssues += [ordered]@{
        code = "missing_sync_script"
        path = $SyncScriptPath
        message = "tools/sync_plugin.ps1 is required to refresh distribution and sandbox plugin copies."
    }
}

if ((-not $SkipSyncPlugin) -and -not (Test-Path -LiteralPath $PluginSourcePath)) {
    $BlockingIssues += [ordered]@{
        code = "missing_plugin_source"
        path = $PluginSourcePath
        message = "addons/godot_agent must exist before plugin sync can run."
    }
}

if ($IncludeSmoke) {
    foreach ($relativePath in $SmokePaths) {
        $absolutePath = Resolve-AbsolutePath -BasePath $RepoRoot -PathValue $relativePath
        if (-not (Test-Path -LiteralPath $absolutePath)) {
            $BlockingIssues += [ordered]@{
                code = "missing_smoke_test"
                path = $absolutePath
                message = "Bootstrap smoke requires the targeted non-live test files."
            }
        }
    }
}

$BootstrapPython = if ($SkipVenv) { $ResolvedPython } else { $VenvPython }
$CreateVenvPython = if ($ResolvedPython) { $ResolvedPython } else { $PythonExe }
$SelectedBootstrapPython = if ($BootstrapPython) { $BootstrapPython } else { $PythonExe }
$CreateVenvArgs = @("-m", "venv")
if ((Test-Path -LiteralPath $VenvPath) -and (-not $VenvReady)) {
    $CreateVenvArgs += "--clear"
}
$CreateVenvArgs += $VenvPath
$Steps = @()
$Steps += New-Step -Id "create_venv" -Title "Create virtual environment" -Enabled (-not $SkipVenv) -Mutates $true -FilePath $CreateVenvPython -Arguments $CreateVenvArgs -Prerequisites @("python_launcher") -Notes "Creates a local .venv for clean-machine installs and clears partial environments when needed." -Executor "native"
$Steps += New-Step -Id "install_requirements" -Title "Install Python dependencies" -Enabled (-not $SkipInstall) -Mutates $true -FilePath $SelectedBootstrapPython -Arguments @("-m", "pip", "install", "-r", $RequirementsPath) -Prerequisites @("requirements.txt") -Notes "Installs repo dependencies into the selected interpreter." -Executor "native"
$Steps += New-Step -Id "sync_plugin" -Title "Sync plugin distribution copies" -Enabled (-not $SkipSyncPlugin) -Mutates $true -FilePath $SyncScriptPath -Arguments @("-RepoRoot", $RepoRoot) -Prerequisites @("tools/sync_plugin.ps1", "addons/godot_agent") -Notes "Keeps godot_plugin/ and sandbox_project/ aligned with addons/godot_agent." -Executor "powershell"
$Steps += New-Step -Id "doctor" -Title "Run environment doctor" -Enabled (-not $SkipDoctor) -Mutates $false -FilePath $SelectedBootstrapPython -Arguments @("-m", "agent_system.cli", "doctor", "--report-path", $DoctorReportPath) -Prerequisites @("config.yaml") -Notes "Produces the first-run self-check report for Python, Godot, plugin sync, directories, and layout." -Executor "native"
$Steps += New-Step -Id "bootstrap_smoke" -Title "Run targeted non-live bootstrap smoke" -Enabled ([bool]$IncludeSmoke) -Mutates $false -FilePath $SelectedBootstrapPython -Arguments $SmokeArgs -Prerequisites @($SmokePaths) -Notes "Optional regression slice for clean-machine verification." -Executor "native"

$Result = [ordered]@{
    ok              = @($BlockingIssues).Count -eq 0
    preview         = [bool]$Preview
    repo_root       = $RepoRoot
    report_path     = $ResolvedReportPath
    doctor_report_path = $ResolvedDoctorReportPath
    temp_root       = $WorkspaceTempRoot
    python          = [ordered]@{
        requested        = $PythonExe
        resolved         = $ResolvedPython
        uses_virtualenv  = -not $SkipVenv
        virtualenv_path  = $VenvPath
        bootstrap_python = $BootstrapPython
        virtualenv_ready = [bool]$VenvReady
    }
    doctor_report   = Get-DoctorReportSummary -ResolvedPath $ResolvedDoctorReportPath -DisplayPath $DoctorReportPath
    blocking_issues = @($BlockingIssues)
    steps           = @($Steps)
}

if ($Preview) {
    $Result | ConvertTo-Json -Depth 8
    exit 0
}

$StepResults = @()
if (@($BlockingIssues).Count -eq 0) {
    Ensure-Directory -PathValue ([System.IO.Path]::GetDirectoryName($ResolvedReportPath))
    Ensure-Directory -PathValue ([System.IO.Path]::GetDirectoryName($ResolvedDoctorReportPath))
    Ensure-Directory -PathValue $WorkspaceTempRoot
    $env:TMP = $WorkspaceTempRoot
    $env:TEMP = $WorkspaceTempRoot

    foreach ($step in $Steps) {
        if ($step.id -eq "create_venv" -and $step.enabled -and $VenvReady) {
            $StepResults += [ordered]@{
                id            = $step.id
                title         = $step.title
                enabled       = $true
                mutates       = $true
                executor      = $step.executor
                command       = $step.command
                prerequisites = @($step.prerequisites)
                notes         = "Skipped because the virtual environment already exists and includes pip."
                status        = "skipped"
            }
            continue
        }

        $stepResult = Invoke-Step -Step $step -WorkingDirectory $RepoRoot
        $StepResults += $stepResult
        if ($stepResult.status -eq "failed") {
            $Result.ok = $false
            $Result.blocking_issues += [ordered]@{
                code = "step_failed"
                path = $step.id
                message = "$($step.title) failed: $($stepResult.error)"
            }
            break
        }
    }
} else {
    $Result.ok = $false
}

$DoctorReportSummary = Get-DoctorReportSummary -ResolvedPath $ResolvedDoctorReportPath -DisplayPath $DoctorReportPath
$Result.doctor_report = $DoctorReportSummary
$DoctorStepResult = $StepResults | Where-Object { $_.id -eq "doctor" } | Select-Object -First 1
if ($DoctorStepResult) {
    $DoctorStepResult["report_path"] = $DoctorReportPath
    $DoctorStepResult["report_exists"] = [bool]$DoctorReportSummary.exists
    $DoctorStepResult["doctor_ok"] = [bool]$DoctorReportSummary.ok
    $DoctorStepResult["doctor_action_item_count"] = [int]$DoctorReportSummary.action_item_count
}

$Result.steps = $StepResults
$json = $Result | ConvertTo-Json -Depth 8

if (@($BlockingIssues).Count -eq 0) {
    Set-Content -LiteralPath $ResolvedReportPath -Value $json -Encoding UTF8
}

$json

if (-not $Result.ok) {
    exit 1
}
