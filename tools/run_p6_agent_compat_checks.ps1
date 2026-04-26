param(
    [switch]$IncludeLive
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

Write-Host "P6 agent compatibility targeted non-live checks"
python -m pytest `
    tests/test_agent_compatibility.py `
    tests/test_api.py `
    tests/test_cli.py `
    tests/test_mcp_server.py `
    tests/test_remote_mcp_bridge.py `
    -q

Write-Host "P6 provider compatibility smoke"
python -m agent_system.cli agent-compat --provider codex,openai_api --json

Write-Host "Full non-live suite"
python -m pytest -m "not live" -q

if ($IncludeLive) {
    Write-Host "Live sandbox checks"
    .\tools\run_live_sandbox_tests.ps1
} else {
    Write-Host "SKIP live sandbox checks. Re-run with -IncludeLive when Godot editor automation is available."
}
