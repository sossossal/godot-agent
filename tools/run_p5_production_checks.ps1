param(
    [switch]$IncludeLive,
    [switch]$IncludeBrowser,
    [switch]$IncludeRemoteMcp
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

Write-Host "P5 production readiness targeted non-live checks"
python -m pytest `
    tests/test_production_scale.py `
    tests/test_production_samples.py `
    tests/test_api.py `
    tests/test_cli.py `
    tests/test_governance.py `
    -q

Write-Host "P5 advisory production readiness smoke"
.\tools\validate_production_readiness.ps1 `
    -ScenarioId vertical_slice_2d `
    -Evidence contract,tests,docs,quality_dashboard `
    -ChangedPath scenes/Main.tscn,scripts/player_controller.gd,README.md `
    -Mode advisory `
    -Json

Write-Host "Full non-live suite"
python -m pytest -m "not live" -q

if ($IncludeLive) {
    Write-Host "Live sandbox checks"
    .\tools\run_live_sandbox_tests.ps1 -PytestArgs @(
        "tests/test_live_sandbox.py",
        "tests/test_live_production_flows.py",
        "-v",
        "-s"
    )
} else {
    Write-Host "SKIP live sandbox checks. Re-run with -IncludeLive when Godot editor automation is available."
}

if ($IncludeBrowser -or $IncludeLive) {
    Write-Host "Portal browser DOM smoke"
    .\tools\run_portal_browser_smoke.ps1
    Write-Host "Portal browser click smoke"
    python .\tools\run_portal_browser_click_smoke.py
} else {
    Write-Host "SKIP Portal browser smoke. Re-run with -IncludeBrowser when Chromium automation is available."
}

if ($IncludeRemoteMcp -or $IncludeLive) {
    Write-Host "Remote MCP live smoke"
    .\tools\run_remote_mcp_live_smoke.ps1
} else {
    Write-Host "SKIP Remote MCP live smoke. Re-run with -IncludeRemoteMcp when HTTP MCP validation is required."
}
