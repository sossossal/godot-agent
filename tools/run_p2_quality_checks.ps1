param(
    [switch]$IncludeLive
)

$ErrorActionPreference = "Stop"

Write-Host "P2 targeted non-live checks"
python -m pytest `
    tests/test_migrations.py `
    tests/test_quality_dashboard.py `
    tests/test_remote_mcp_bridge.py `
    tests/test_template_registry.py `
    tests/test_mcp_server.py `
    -q

Write-Host "Full non-live suite"
python -m pytest -m "not live" -q

if ($IncludeLive) {
    Write-Host "Live sandbox checks"
    .\tools\run_live_sandbox_tests.ps1
} else {
    Write-Host "SKIP live sandbox checks. Re-run with -IncludeLive when Godot editor automation is available."
}
