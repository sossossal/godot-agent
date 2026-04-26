param(
    [string]$ScenarioId = "vertical_slice_2d",
    [string[]]$Evidence = @(),
    [string[]]$ChangedPath = @(),
    [ValidateSet("strict", "advisory")]
    [string]$Mode = "strict",
    [switch]$FailOnWarnings,
    [switch]$Json,
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$argsList = @(
    "-m", "agent_system.cli",
    "production",
    "--scenario-id", $ScenarioId,
    "--mode", $Mode
)

if ($Evidence.Count -gt 0) {
    $argsList += @("--evidence", ($Evidence -join ","))
}

if ($ChangedPath.Count -gt 0) {
    $argsList += @("--changed-path", ($ChangedPath -join ","))
}

if ($FailOnWarnings) {
    $argsList += "--fail-on-warnings"
}

if ($Json) {
    $argsList += "--json"
}

if ($ProjectRoot) {
    $argsList += @("--project-root", $ProjectRoot)
}

python @argsList
exit $LASTEXITCODE
